"""
================
Metadata Routing
================

.. currentmodule:: sklearn

This document shows how you can use the metadata routing mechanism in
scikit-learn to route metadata through meta-estimators to the estimators using
them. To better understand the rest of the document, we need to introduce two
concepts: routers and consumers. A router is an object, in most cases a
meta-estimator, which routes given data and metadata to other objects and
estimators. A consumer, on the other hand, is an object which accepts and uses
a certain given metadata. For instance, an estimator taking into account
``sample_weight`` is a consumer of ``sample_weight``. It is possible for an
object to be both a router and a consumer. For instance, a meta-estimator may
take into account ``sample_weight`` in certain calculations, but it may also
route it to the underlying estimator.

First a few imports and some random data for the rest of the script.
"""
# %%

import numpy as np
import warnings
from sklearn.base import BaseEstimator
from sklearn.base import ClassifierMixin
from sklearn.base import RegressorMixin
from sklearn.base import MetaEstimatorMixin
from sklearn.base import TransformerMixin
from sklearn.base import clone
from sklearn.utils.metadata_requests import RequestType
from sklearn.utils.metadata_requests import metadata_request_factory
from sklearn.utils.metadata_requests import MetadataRouter
from sklearn.utils.metadata_requests import MethodMapping
from sklearn.utils.validation import check_is_fitted
from sklearn.linear_model import LinearRegression

N, M = 100, 4
X = np.random.rand(N, M)
y = np.random.randint(0, 2, size=N)
my_groups = np.random.randint(0, 10, size=N)
my_weights = np.random.rand(N)
my_other_weights = np.random.rand(N)

# %%
# Estimators
# ----------
# Here we demonstrate how an estimator can expose the required API to support
# metadata routing as a consumer. Imagine a simple classifier accepting
# ``sample_weight`` as a metadata on its ``fit`` and ``groups`` in its
# ``predict`` method. We add two constructor arguments to helps us check
# whether an expected metadata is given or not. This is a minimal scikit-learn
# compatible classifier:


class ExampleClassifier(ClassifierMixin, BaseEstimator):
    def __init__(self, sample_weight_is_none=True, groups_is_none=True):
        self.sample_weight_is_none = sample_weight_is_none
        self.groups_is_none = groups_is_none

    def fit(self, X, y, sample_weight=None):
        if (sample_weight is None) != self.sample_weight_is_none:
            raise ValueError(
                "sample_weight's value and sample_weight_is_none disagree!"
            )
        # all classifiers need to expose a classes_ attribute once they're fit.
        self.classes_ = np.array([0, 1])
        return self

    def predict(self, X, groups=None):
        if (groups is None) != self.groups_is_none:
            raise ValueError("groups's value and groups_is_none disagree!")
        # return a constant value of 1, not a very smart classifier!
        return np.ones(len(X))


# %%
# The above estimator now has all it needs to consume metadata. This is done
# by some magic done in :class:`~base.BaseEstimator`. There are now three
# methods exposed by the above class: ``fit_requests``, ``predict_requests``,
# and ``get_metadata_routing``.
#
# By default, no metadata is requested, which we can see as:

ExampleClassifier().get_metadata_routing()

# %%
# The above output means that ``sample_weight`` and ``groups`` are not
# requested, but if a router is given those metadata, it should raise an error,
# since the user has not explicitly set whether they are required or not. The
# same is true for ``sample_weight`` in ``score`` method, which is inherited
# from :class:`~base.ClassifierMixin`. In order to explicitly set request
# values for those metadata, we can use these methods:

est = (
    ExampleClassifier().fit_requests(sample_weight=False).predict_requests(groups=True)
)
est.get_metadata_routing()

# %%
# As you can see, now the two metadata have explicit request values, one is
# requested and the other one is not. Instead of ``True`` and ``False``, we
# could also use the :class:`~sklearn.utils.metadata_requests.RequestType`
# values.

est = (
    ExampleClassifier()
    .fit_requests(sample_weight=RequestType.UNREQUESTED)
    .predict_requests(groups=RequestType.REQUESTED)
)
est.get_metadata_routing()

# %%
# Please note that as long as the above estimator is not used in another
# meta-estimator, the user does not need to set any requests for the metadata.
# A simple usage of the above estimator would work as expected. Remember that
# ``{sample_weight, groups}_is_none`` are for testing/demonstration purposes
# and don't have anything to do with the routing mechanisms.

est = ExampleClassifier(sample_weight_is_none=False, groups_is_none=False)
est.fit(X, y, sample_weight=my_weights)
est.predict(X[:3, :], groups=my_groups)

# %%
# Now let's have a meta-estimator, which doesn't do much other than routing the
# metadata correctly.


class MetaClassifier(MetaEstimatorMixin, ClassifierMixin, BaseEstimator):
    def __init__(self, estimator):
        self.estimator = estimator

    def fit(self, X, y, **fit_params):
        if self.estimator is None:
            raise ValueError("estimator cannot be None!")

        # meta-estimators are responsible for validating the given metadata
        request_router = metadata_request_factory(self)
        request_router.validate_metadata(params=fit_params, method="fit")
        # we can use provided utility methods to map the given metadata to what
        # is required by the underlying estimator
        params = request_router.get_params(params=fit_params, method="fit")

        self.estimator_ = clone(self.estimator).fit(X, y, **params.estimator.fit)
        self.classes_ = self.estimator_.classes_
        return self

    def predict(self, X, **predict_params):
        check_is_fitted(self)
        # same as in ``fit``, we validate the given metadata
        request_router = metadata_request_factory(self)
        request_router.validate_metadata(params=predict_params, method="predict")
        # and then prepare the input to the underlying ``predict`` method.
        params = request_router.get_params(params=predict_params, method="predict")
        return self.estimator_.predict(X, **params.estimator.predict)

    def get_metadata_routing(self):
        router = MetadataRouter().add(
            estimator=self.estimator, method_mapping="one-to-one"
        )
        return router.to_dict()


# %%
# Let's break down different parts of the above code.
#
# First, the :method:`~utils.metadata_requests.metadata_request_factory` takes
# an object from which a :class:`~utils.metadata_requests.MetadataRequest` can
# be constructed. This may be an estimator, or a dictionary representing a
# ``MetadataRequest`` object. If an estimator is given, it tries to call the
# estimator and construct the object from that, and if the estimator doesn't
# have such a method, then a default empty ``MetadataRequest`` is returned.
#
# Then in each method, we use the corresponding
# :method:`~utils.metadata_requests.MethodMetadataRequest.get_input` to
# construct a dictionary of the form ``{"metadata": value}`` to pass to the
# underlying estimator's method. Please note that since in this example the
# meta-estimator does not consume any of the given metadata itself, and there
# is only one object to which the metadata is passed, we have
# ``ignore_extras=False`` which means passed metadata are also validated in the
# sense that it will be checked if anything extra is given. This is to avoid
# silent bugs, and this is how it will work:

est = MetaClassifier(
    estimator=ExampleClassifier(sample_weight_is_none=False).fit_requests(
        sample_weight=True
    )
)
est.fit(X, y, sample_weight=my_weights)

# %%
# Note that the above example checks that ``sample_weight`` is correctly passed to
# ``ExampleClassifier``, or else it would have raised:

try:
    est.fit(X, y)
except ValueError as e:
    print(e)

# %%
# If we pass an unknown metadata, it will be caught:
try:
    est.fit(X, y, test=my_weights)
except ValueError as e:
    print(e)

# %%
# And if we pass something which is not explicitly requested:
try:
    est.fit(X, y, sample_weight=my_weights).predict(X, groups=my_groups)
except ValueError as e:
    print(e)

# %%
# Also, if we explicitly say it's not requested, but pass it:
est = MetaClassifier(
    estimator=ExampleClassifier(sample_weight_is_none=False)
    .fit_requests(sample_weight=True)
    .predict_requests(groups=False)
)
try:
    est.fit(X, y, sample_weight=my_weights).predict(X[:3, :], groups=my_groups)
except ValueError as e:
    print(e)

# %%
# In order to understand the above implementation of ``get_metadata_routing``,
# we need to also introduce an aliased metadata. This is when an estimator
# requests a metadata with a different name than the default value. For
# instance, in a setting where there are two estimators in a pipeline, one
# could request ``sample_weight1`` and the other ``sample_weight2``. Note that
# this doesn't change what the estimator expects, it only tells the
# meta-estimator how to map provided metadata to what's required. Here's an
# example, where we pass ``aliased_sample_weight`` to the meta-estimator, but
# the meta-estimator understands that ``aliased_sample_weight`` is an alias for
# ``sample_weight``, and passes it as ``sample_weight`` to the underlying
# estimator:
est = MetaClassifier(
    estimator=ExampleClassifier(sample_weight_is_none=False).fit_requests(
        sample_weight="aliased_sample_weight"
    )
)
est.fit(X, y, aliased_sample_weight=my_weights)

# %%
# And passing ``sample_weight`` here will fail since it is requested with an alias:
try:
    est.fit(X, y, sample_weight=my_weights)
except ValueError as e:
    print(e)

# %%
# This leads us to the ``get_metadata_routing``. The way routing works in
# scikit-learn is that consumers request what they need, and routers pass that
# along. But another thing a router does, is that it also exposes what it
# requires so that it can be used as a consumer inside another router, e.g. a
# pipeline inside a grid search object. However, routers (e.g. our
# meta-estimator) don't expose the mapping, and only expose what's required for
# them to do their job. In the above example, it looks like the following:
est.get_metadata_routing()

# %%
# As you can see, the only metadata requested for method ``fit`` is
# ``"aliased_sample_weight"``. This information is enough for another
# meta-estimator/router to know what needs to be passed to ``est``. In other
# words, ``sample_weight`` is *masked* . The ``MetadataRouter`` class enables us to
# easily create the routing object which would create the output we need for
# our ``get_metadata_routing``. In the above implementation,
# ``mapping="one-to-one"`` means all requests are mapped one to one from the
# sub-estimator to the meta-estimator's methods, and ``mask=True`` indicates
# that the requests should be masked, as explained. Masking is necessary since
# it's the meta-estimator which does the mapping between the alias and the
# original metadata name. Without it, having ``est`` in another meta-estimator
# would break the routing. Imagine this example:

meta_est = MetaClassifier(estimator=est).fit(X, y, aliased_sample_weight=my_weights)

# %%
# In the above example, this is how each ``fit`` method will call the
# sub-estimator's ``fit``::
#
#     meta_est.fit(X, y, aliased_sample_weight=my_weights):
#         ...  # this estimator (est), expects aliased_sample_weight as seen above
#         self.estimator_.fit(X, y, aliased_sample_weight=aliased_sample_weight):
#             ...  # est passes aliased_sample_weight's value as sample_weight,
#                  # which is expected by the sub-estimator
#             self.estimator_.fit(X, y, sample_weight=aliased_sample_weight)
#    ...

# %%
# Router and Consumer
# -------------------
# To show how a slightly more complicated case would work, consider a case
# where a meta-estimator uses some metadata, but it also routes them to an
# underlying estimator. In this case, this meta-estimator is a consumer and a
# router at the same time. This is how we can implement one, and it is very
# similar to what we had before, with a few tweaks.


class RouterConsumerClassifier(MetaEstimatorMixin, ClassifierMixin, BaseEstimator):
    def __init__(self, estimator, sample_weight_is_none=True):
        self.estimator = estimator
        self.sample_weight_is_none = sample_weight_is_none

    def fit(self, X, y, sample_weight, **fit_params):
        if self.estimator is None:
            raise ValueError("estimator cannot be None!")

        if (sample_weight is None) != self.sample_weight_is_none:
            raise ValueError(
                "sample_weight's value and sample_weight_is_none disagree!"
            )

        if sample_weight is not None:
            fit_params["sample_weight"] = sample_weight

        # meta-estimators are responsible for validating the given metadata
        request_router = metadata_request_factory(self)
        request_router.validate_metadata(params=fit_params, method="fit")
        # we can use provided utility methods to map the given metadata to what
        # is required by the underlying estimator
        params = request_router.get_params(params=fit_params, method="fit")
        self.estimator_ = clone(self.estimator).fit(X, y, **params.estimator.fit)
        self.classes_ = self.estimator_.classes_
        return self

    def predict(self, X, **predict_params):
        check_is_fitted(self)
        # same as in ``fit``, we validate the given metadata
        request_router = metadata_request_factory(self)
        request_router.validate_metadata(params=predict_params, method="predict")
        # and then prepare the input to the underlying ``predict`` method.
        params = request_router.get_params(params=predict_params, method="predict")
        return self.estimator_.predict(X, **params.estimator.predict)

    def get_metadata_routing(self):
        router = (
            MetadataRouter()
            .add_self(self)
            .add(estimator=self.estimator, method_mapping="one-to-one")
        )
        return router.to_dict()


# %%
# The two key parts where the above estimator differs from our previous
# meta-estimator is validation in ``fit``, and generating routing data in
# ``get_metadata_routing``. In ``fit``, we pass ``self_metadata=super()`` to
# ``validate_metadata``. This is important since consumers don't validate how
# metadata is passed to them, it's only done by routers. In this case, this
# means validation should be done for the metadata consumed by the
# sub-estimator, but not for the metadata consumed by the meta-estimator
# itself.
#
# In ``get_metadata_routing``, we add what's consumed by this meta-estimator
# without masking them, before adding what's requested by the sub-estimator.
# Passing ``super()`` here means only what's explicitly mentioned in the
# methods' signature is considered as metadata consumed by this estimator; in
# this case fit's ``sample_weight``. Let's see what the routing metadata looks like with
# different settings:

# %%
# no metadata requested
est = RouterConsumerClassifier(estimator=ExampleClassifier())
est.get_metadata_routing()


# %%
# ``sample_weight`` requested by child estimator
est = RouterConsumerClassifier(
    estimator=ExampleClassifier().fit_requests(sample_weight=True)
)
est.get_metadata_routing()
# %%
# ``sample_weight`` requested by meta-estimator
est = RouterConsumerClassifier(estimator=ExampleClassifier()).fit_requests(
    sample_weight=True
)
est.get_metadata_routing()

# %%
# As you can see, the last two are identical, which is fine since that's what a
# meta-estimator having ``RouterConsumerClassifier`` as a sub-estimator needs.
# The situation is different if we use named aliases:
#
# Aliased on both
est = RouterConsumerClassifier(
    sample_weight_is_none=False,
    estimator=ExampleClassifier(sample_weight_is_none=False).fit_requests(
        sample_weight="clf_sample_weight"
    ),
).fit_requests(sample_weight="meta_clf_sample_weight")
est.get_metadata_routing()

# %%
# However, ``fit`` of the meta-estimator only needs the alias for the
# sub-estimator:
est.fit(X, y, sample_weight=my_weights, clf_sample_weight=my_other_weights)

# %%
# Alias only on the sub-estimator. This is useful if we don't want the
# meta-estimator to use the metadata, and we only want the metadata to be used
# by the sub-estimator.
est = RouterConsumerClassifier(
    estimator=ExampleClassifier().fit_requests(sample_weight="aliased_sample_weight")
).fit_requests(sample_weight=True)
est.get_metadata_routing()

# %%
# Alias only on the meta-estimator. This example raises an error since there
# will be two conflicting values for routing ``sample_weight``.
est = RouterConsumerClassifier(
    estimator=ExampleClassifier().fit_requests(sample_weight=True)
).fit_requests(sample_weight="aliased_sample_weight")
try:
    est.get_metadata_routing()
except ValueError as e:
    print(e)


# %%
# Simple Pipeline
# ---------------
# A slightly more complicated use-case is a meta-estimator which does something
# similar to the ``Pipeline``. Here is a meta-estimator, which accepts a
# transformer and a classifier, and applies the transformer before running the
# classifier.


class SimplePipeline(ClassifierMixin, BaseEstimator):
    _required_parameters = ["estimator"]

    def __init__(self, transformer, classifier):
        self.transformer = transformer
        self.classifier = classifier

    def fit(self, X, y, **fit_params):
        request_routing = metadata_request_factory(self)
        request_routing.validate_metadata(params=fit_params, method="fit")
        params = request_routing.get_params(params=fit_params, method="fit")

        self.transformer_ = clone(self.transformer).fit(X, y, **params.transformer.fit)
        X_transformed = self.transformer_.transform(X, **params.transformer.transform)

        self.classifier_ = clone(self.classifier).fit(
            X_transformed, y, **params.classifier.fit
        )
        return self

    def predict(self, X, **predict_params):
        request_routing = metadata_request_factory(self)
        request_routing.validate_metadata(params=predict_params, method="predict")
        params = request_routing.get_params(params=predict_params, method="predict")

        X_transformed = self.transformer_.transform(X, **params.transformer.transform)
        return self.classifier_.predict(X_transformed, **params.classifier.predict)

    def get_metadata_routing(self):
        router = (
            MetadataRouter()
            .add(
                transformer=self.transformer,
                method_mapping=MethodMapping()
                .add(method="fit", used_in="fit")
                .add(method="transform", used_in="fit")
                .add(method="transform", used_in="predict"),
            )
            .add(classifier=self.classifier, method_mapping="one-to-one")
        )
        return router.to_dict()


# %%
# As you can see, we use the transformer's ``transform`` and ``fit`` methods in
# ``fit``, and its ``transform`` method in ``predict``, and that's what you see
# implemented in the routing structure of the pipeline class. In order to test
# the above pipeline, let's add an example transformer.


class ExampleTransformer(TransformerMixin, BaseEstimator):
    def fit(self, X, y, sample_weight=None):
        if sample_weight is None:
            raise ValueError("sample_weight is None!")
        return self

    def transform(self, X, groups=None):
        if groups is None:
            raise ValueError("groups is None!")
        return X


# %%
# Now we can test our pipeline, and see if metadata is correctly passed around.
# This example uses our simple pipeline, and our transformer, and our
# consumer+router estimator which uses our simple classifier.

est = SimplePipeline(
    transformer=ExampleTransformer()
    # we transformer's fit to receive sample_weight
    .fit_requests(sample_weight=True)
    # we want transformer's transform to receive groups
    .transform_requests(groups=True),
    classifier=RouterConsumerClassifier(
        sample_weight_is_none=False,
        estimator=ExampleClassifier(sample_weight_is_none=False)
        # we want this sub-estimator to receive sample_weight in fit
        .fit_requests(sample_weight=True)
        # but not groups in predict
        .predict_requests(groups=False),
    ).fit_requests(
        # and we want the meta-estimator to receive sample_weight as well
        sample_weight=True
    ),
)
est.fit(X, y, sample_weight=my_weights, groups=my_groups).predict(
    X[:3], groups=my_groups
)

# %%
# Deprecation / Default Value Change
# -----------------------------------
# In this section we show how one should handle the case where a router becomes
# also a consumer, especially when it consumes the same metadata as its
# sub-estimator. In this case, a warning should be raised for a while, to let
# users know the behavior is changed from previous versions.


class MetaRegressor(MetaEstimatorMixin, RegressorMixin, BaseEstimator):
    def __init__(self, estimator):
        self.estimator = estimator

    def fit(self, X, y, **fit_params):
        request_routing = metadata_request_factory(self)
        request_routing.validate_metadata(params=fit_params, method="fit")
        params = request_routing.get_params(params=fit_params, method="fit")
        self.estimator_ = clone(self.estimator).fit(X, y, **params.estimator.fit)

    def get_metadata_routing(self):
        router = MetadataRouter().add(
            estimator=self.estimator, method_mapping="one-to-one"
        )
        return router.to_dict()


# %%
# As explained above, this is now a valid usage:

reg = MetaRegressor(estimator=LinearRegression().fit_requests(sample_weight=True))
reg.fit(X, y, sample_weight=my_weights)


# %%
# Now imagine we further develop ``MetaRegressor`` and it now also *consumes*
# ``sample_weight``:


class SampledMetaRegressor(MetaEstimatorMixin, RegressorMixin, BaseEstimator):
    __metadata_request__fit = {"sample_weight": RequestType.WARN}

    def __init__(self, estimator):
        self.estimator = estimator

    def fit(self, X, y, sample_weight=None, **fit_params):
        if sample_weight is not None:
            fit_params["sample_weight"] = sample_weight
        request_routing = metadata_request_factory(self)
        request_routing.validate_metadata(params=fit_params, method="fit")
        params = request_routing.get_params(params=fit_params, method="fit")
        self.estimator_ = clone(self.estimator).fit(X, y, **params.estimator.fit)

    def get_metadata_routing(self):
        router = (
            MetadataRouter()
            .add_self(self)
            .add(estimator=self.estimator, method_mapping="one-to-one")
        )
        return router.to_dict()


# %%
# The above implementation is almost no different than ``MetaRegressor``, and
# because of the default request value defined in `__metadata_request__fit``
# there is a warning raised.

with warnings.catch_warnings(record=True) as record:
    SampledMetaRegressor(
        estimator=LinearRegression().fit_requests(sample_weight=False)
    ).fit(X, y, sample_weight=my_weights)
for w in record:
    print(w.message)


# %%
# When an estimator suports a metadata which wasn't supported before, the
# following pattern can be used to warn the users about it.


class ExampleRegressor(RegressorMixin, BaseEstimator):
    __metadata_request__fit = {"sample_weight": RequestType.WARN}

    def fit(self, X, y, sample_weight=None):
        return self

    def predict(self, X):
        return np.zeros(shape=(len(X)))


with warnings.catch_warnings(record=True) as record:
    MetaRegressor(estimator=ExampleRegressor()).fit(X, y, sample_weight=my_weights)
for w in record:
    print(w.message)
