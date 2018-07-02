import json
import numbers
import sys
import os
from os.path import join, exists
from warnings import warn

try:
    # Python 2
    from urllib2 import urlopen
except ImportError:
    # Python 3+
    from urllib.request import urlopen


from scipy.io.arff import loadarff
import numpy as np

from .base import get_data_home
from ..externals.joblib import Memory
from ..externals.six import StringIO
from ..externals.six.moves.urllib.error import HTTPError
from ..utils import Bunch

_SEARCH_NAME = "https://openml.org/api/v1/json/data/list/data_name/{}/limit/1"
_DATA_INFO = "https://openml.org/api/v1/json/data/{}"
_DATA_FEATURES = "https://openml.org/api/v1/json/data/features/{}"


def _get_data_info_by_name(name, version):
    data_found = True
    try:
        if version == "active":
            json_string = urlopen(_SEARCH_NAME.format(name
                                                      + "/status/active/"))
        else:
            json_string = urlopen(_SEARCH_NAME.format(name)
                                  + "/data_version/{}".format(version))
    except HTTPError as error:
        if error.code == 412:
            data_found = False
        else:
            raise error

    if not data_found and version != "active":
        # might have been deactivated. will warn later
        data_found = True
        try:
            json_string = urlopen(_SEARCH_NAME.format(name) +
                                  "/data_version/{}/status/deactivated".format(
                                      version))
        except HTTPError as error:
            if error.code == 412:
                data_found = False
            else:
                raise error

    if not data_found:
        # not in except for nicer traceback
        if version == "active":
            raise ValueError("No active dataset {} found.".format(name))
        raise ValueError("Dataset {} with version {}"
                         " not found.".format(name, version))

    json_data = json.loads(json_string.read().decode("utf-8"))
    return json_data['data']['dataset'][0]


def _get_data_description_by_id(data_id):
    data_found = True
    try:
        json_string = urlopen(_DATA_INFO.format(data_id))
    except HTTPError as error:
        if error.code == 412:
            data_found = False
    if not data_found:
        # not in except for nicer traceback
        raise ValueError("Dataset with id {} "
                         "not found.".format(data_id))
    json_data = json.loads(json_string.read().decode("utf-8"))
    return json_data['data_set_description']


def _get_data_features(data_id):
    data_found = True
    try:
        json_string = urlopen(_DATA_FEATURES.format(data_id))
    except HTTPError as error:
        if error.code == 412:
            data_found = False
    if not data_found:
        # not in except for nicer traceback
        raise ValueError("Dataset with id {} "
                         "not found.".format(data_id))
    json_data = json.loads(json_string.read().decode("utf-8"))
    return json_data['data_features']['feature']


def _download_data(url):
    response = urlopen(url)
    if sys.version_info[0] == 2:
        # Python2.7 numpy can't handle unicode?
        arff = loadarff(StringIO(response.read()))
    else:
        arff = loadarff(StringIO(response.read().decode('utf-8')))

    response.close()
    return arff


def _download_data_csv(file_id):
    response = urlopen("https://openml.org/data/v1/get_csv/{}".format(file_id))
    data = np.genfromtxt(response, names=True, dtype=None, delimiter=',',
                         missing_values='?')
    response.close()
    return data


def fetch_openml(name_or_id=None, version='active', data_home=None,
                 target_column='default-target', memory=True):
    """Fetch dataset from openml by name or dataset id.

    Datasets are uniquely identified by either an integer ID or by a
    combination of name and version (i.e. there might be multiple
    versions of the 'iris' dataset).

    Parameters
    ----------
    name_or_id : string or integer
        Identifier of the dataset. If integer, assumed to be the id of the
        dataset on OpenML, if string, assumed to be the name of the dataset.

    version : integer or 'active', default='active'
        Version of the dataset. Only used if ``name_or_id`` is a string.
        If 'active' the oldest version that's still active is used.

    data_home : string or None, default None
        Specify another download and cache folder for the data sets. By default
        all scikit-learn data is stored in '~/scikit_learn_data' subfolders.

    target_column : string or None, default 'default-target'
        Specify the column name in the data to use as target. If
        'default-target', the standard target column a stored on the server
        is used. If ``None``, all columns are returned as data and the
        tharget is ``None``.

    memory : boolean, default=True
        Whether to store downloaded datasets using joblib.

    Returns
    -------

    data : Bunch
        Dictionary-like object, the interesting attributes are:
        'data', the data to learn, 'target', the regression target or
        classification labels, 'DESCR', the full description of the dataset,
        'feature_names', the original names of the dataset columns, and
        'details' which provide more information on the openml meta-data.
    """
    data_home = get_data_home(data_home=data_home)
    data_home = join(data_home, 'openml')
    if memory:
        mem = Memory(join(data_home, 'cache'), verbose=0).cache
    else:
        def mem(func):
            return func
    _get_data_info_by_name_ = mem(_get_data_info_by_name)
    _get_data_description_by_id_ = mem(_get_data_description_by_id)
    _get_data_features_ = mem(_get_data_features)
    _download_data_csv_ = mem(_download_data_csv)

    if not exists(data_home):
        os.makedirs(data_home)

    # check if dataset id is known
    if isinstance(name_or_id, numbers.Integral):
        if version != "active":
            raise ValueError(
                "Dataset id={} and version={} passed, but you can only "
                "specify a numeric id or a version, not both.".format(
                    name_or_id, version))
        data_id = name_or_id
    elif isinstance(name_or_id, str):
        data_info = _get_data_info_by_name_(name_or_id, version)
        data_id = data_info['did']

    else:
        raise TypeError(
            "Invalid name_or_id {}, should be string or integer.".format(
                name_or_id))

    data_description = _get_data_description_by_id_(data_id)
    if data_description['status'] != "active":
        warn("Version {} of dataset {} is inactive, meaning that issues have"
             " been found in the dataset. Try using a newer version.".format(
                 data_description['version'], data_description['name']))
    if target_column == "default-target":
        target_column = data_description.get('default_target_attribute', None)

    # download actual data
    features = _get_data_features_(data_id)
    # TODO: stacking the content of the structured array
    # this results in a copy. If the data was homogeneous
    # and target at start or end, we could use a view instead.
    data_columns = []
    for feature in features:
        if (feature['name'] != target_column and feature['is_ignore'] ==
                'false' and feature['is_row_identifier'] == 'false'):
            data_columns.append(feature['name'])

    data = _download_data_csv_(data_description['file_id'])
    if target_column is not None:
        y = data[target_column]
    else:
        y = None

    if all([feature['data_type'] == "numeric" for feature in features
            if feature['name'] in data_columns]):
        dtype = None
    else:
        dtype = object
    X = np.array([data[c] for c in data_columns], dtype=dtype).T

    description = u"{}\n\nDownloaded from openml.org.".format(
        data_description.pop('description'))

    bunch = Bunch(
        data=X, target=y, feature_names=data_columns,
        DESCR=description, details=data_description, features=features,
        url="https://www.openml.org/d/{}".format(data_id))

    return bunch
