.. currentmodule:: sklearn

.. _glossary:

=========================================
Glossary of Common Terms and API Elements
=========================================

This glossary hopes to definitively represent the tacit and explicit
conventions applied in Scikit-learn and its API, while providing a reference
for users and contributors. It aims to describe the concepts and either detail
their corresponding API or link to other relevant parts of the documentation
which do so.

General Concepts
================

.. glossary::

    API
        TODO

        The specific interfaces for estimators implemented in Scikit-learn and
        the generalized conventions across types of estimators as described in
        this glossary.

        TODO: Conventions about what's public and what's not.

    array-like

        The most common data format for *input* to Scikit-learn estimators and
        functions, array-like is any type object for which
        :func:`numpy.asarray` will produce an array of appropriate shape
        (usually 1 or 2-dimensional) of appropriate dtype (usually numeric).

        This includes:

        * a numpy array
        * a list of numbers
        * a list of length-k lists of numbers for some fixed length k
        * a :class:`pandas.DataFrame` with all columns numeric
        * a numeric :class:`pandas.Series`

        It excludes:

        * a :term:`sparse matrix`
        * an iterator
        * a generator

        Note that *output* from scikit-learn estimators and functions (e.g.
        predictions) should generally be arrays or sparse matrices, or lists
        thereof. An estimator where ``predict()`` returns a list or a Series is
        not valid.

    attribute
    attributes

        We mostly use *attribute* to refer to how model information is stored
        on an estimator during fitting.  Public attributes on Scikit-learn
        estimators conventionally begin with an alphabetic character and end
        with a single underscore (``_``) -- for instance ``coef_`` -- are
        available as attributes (in the Python object sense) of a
        :term:`fitted` estimator, and are described in the estimator's
        docstring.

        The information stored in attributes are usually either: sufficient
        statistics used for prediction or transformation; or diagnostic data,
        such as :term:`feature_importances_`.

        Common attributes are listed :ref:`below <glossary_attributes>`.

    backwards compatibility
        We generally try to maintain backwards compatibility (i.e. interfaces
        and behaviors may be extended but not changed or removed) from release
        to release but this comes with some exceptions:

        Public API only
            The behaviour of objects accessed through private identifiers
            (those beginning ``_``) may be changed arbitrarily between
            versions.
        As documented
            We will generally assume that the users have adhered to the
            documented parameter types and ranges. If the documentation asks
            for a list and the user gives a tuple, we do not assure consistent
            behavior from version to version.
        Deprecation
            Behaviors may change following a :term:`deprecation` period
            (usually two releases long).  Warnings are issued using Python's
            :mod:`warnings` module.
        Keyword arguments
            We may sometimes assume that all optional parameters (other than X
            and y to :term:`fit` and similar methods) are passed as keyword
            arguments only and may be positionally reordered.
        Bug fixes and enhancements
            Bug fixes and -- less often -- enhancements may change the behavior
            of estimators, including the predictions of an estimator trained on
            the same data and :term:`random_state`.  When this happens, we
            attempt to note it clearly in the changelog.
        Serialization
            We make no assurances that pickling an estimator in one version
            will allow it to be unpickled to an equivalent model in the
            subsequent version.  See :ref:`persistence_limitations`.
        :func:`utils.estimator_checks.check_estimator`
            TODO We provide limited backwards compatibility assurances for the
            estimator checks. TODO

        Despite this informal contract with our users, the software is provided
        as is, as stated in the licence.  When a release inadvertently
        introduces changes that are not backwards compatible, these are known
        as software regressions.

    categorical feature
        TODO

    clone
        To copy an :term:`estimator instance` and create a new one with
        identical :term:`parameters`, but without any fitted
        :term:`attributes`, using :func:`~skelarn.base.clone`.

        When ``fit`` is called, a :term:`meta-estimator` usually clones
        a wrapped estimator instance before fitting the cloned instance.
        (Exceptions, for legacy reasons, include
        :class:`~pipeline.Pipeline` and
        :class:`~pipeline.FeatureUnion`.)

    common tests
        This refers to the tests run on almost every estimator class in
        Scikit-learn to check they comply with basic API conventions.  They are
        available for external use through
        :func:`utils.estimator_checks.check_estimator`.

        Note: Some exceptions to the common testing regime are currently
        hard-coded into the library, but we hope to replace this by marking
        exceptional behaviours on the estimator using semantic :term:`estimator
        tags`.

    deprecation
        We use deprecation to slowly violate our :term:`backwards
        compatibility` assurances, usually to to:

        * change the semantics of the default value of a parameter; or
        * remove a parameter, attribute, method, class, etc.

        We will ordinarily issue a warning when a deprecated element is used,
        although there may be limitations to this.  For instance, we will raise
        a warning when someone sets a parameter that has been deprecated, but
        may not when they access that parameter's attribute on the estimator
        instance.

        See the :ref:`Contributors' Guide <contributing_deprecation>`.

    docstring
        TODO

    double underscore notation
        When specifying parameter names for nested estimators, ``__`` may be
        used to separate between parent and child.
        See :term:`parameter`.

    dtype
    data type
        TODO. Mention casting.

    duck typing
        TODO
        Note that ``getattr`` should be preferred to ``hasattr`` since
        ``hasattr`` can be expensive, particularly for some model attributes.

    estimator instance
        We sometimes use this terminology to distinguish an :term:`estimator`
        class from a constructed instance. For example, in the following,
        ``cls`` is an estimator class, while ``est1`` and ``est2`` are
        instances::

            cls = RandomForestClassifier
            est1 = cls()
            est2 = RandomForestClassifier()

    examples
        We try to give examples of basic usage for most functions and
        classes in the API:

        * as doctests in their docstrings (i.e. within the ``sklearn/`` library
          code itself).
        * as examples in the :ref:`example gallery <general_examples>`
          rendered from scripts in the ``examples/`` directory, exemplifying
          key features or parameters of the estimator/function.
        * sometimes in the :ref:`User Guide <user_guide>` (built from ``doc/``)
          alongside a technical description of the estimator.

    evaluation metric
        TODO

    estimator tags
        A proposed feature (e.g. :issue:`8022`) by which the capabilities of an
        estimator are described through a set of semantic tags.  This would
        enable some runtime behaviors based on estimator inspection, but it
        also allows each estimator to be tested for appropriate invariances
        while being excepted from other :term:`common tests`.

        Some aspects of estimator tags are currently determined through
        the :term:`duck typing` of methods like ``predict_proba`` and through
        some special attributes on estimator objects:

        ``_estimator_type``
            This string-valued attribute identifies an estimator as being a
            classifier, regressor, etc. It is set by mixins such as
            :class:`base.ClassifierMixin`, but needs to be more explicitly
            adopted on a :term:`meta-estimator`.  Its value should usually be
            checked by way of a helper such as :func:`base.is_classifier`.

        ``_pairwise``
            This boolean attribute indicates whether the data (``X``) passed to
            :func:`fit` and similar methods consists of pairwise measures over
            samples rather than a feature representation for each sample.  It
            is usually ``True`` where an estimator has a ``metric`` or
            ``affinity`` or ``kernel`` parameter with value 'precomputed'.

    feature
    features
        A feature is a function mapping a sampled object to a numeric or
        categorical quantity.  "Feature" is also commonly used to refer to
        these quantities, being the individual elements of a vector
        representing a sample. In a data matrix, features are represented as
        columns: each column contains the result of applying a feature
        function to a set of samples.

        Elsewhere features are known as attributes, predictors, regressors, or
        independent variables.

        Features in scikit-learn are generally expected to be numeric and
        finite, even when they have semantically distinct domains and
        distributions (categorical, ordinal, count-valued, real-valued,
        interval). See also :term`categorical feature` and :term:`missing
        values`.

        ``n_features`` indicates the number of features in a dataset.

    fitting
        Calling :term:`fit` (or :term:`fit_transform`, :term:`fit_predict`,
        etc.) on an estimator.

    fitted
        The state of an estimator after :term:`fitting`.

    function
        TODO

        Talk about where estimator fit or fit_transform functionality is present in a function.

    joblib
        A Python library (http://joblib.readthedocs.io) used in Scikit-learn to
        facilite simple parallelism and caching.  Joblib is oriented towards
        efficiently working with numpy arrays, such as through use of
        :term:`memory mapping`.

    leakage
    data leakage
        A problem in cross validation where generalization performance can be
        over-estimated since knowledge of the test data was inadvertently
        included in training a model.  This is a risk, for instance, when
        applying a :term:`transformer` to the entirety of a dataset rather
        than each training portion in a cross validation split.

        We aim to provide interfaces (such as :mod:`pipeline` and
        :mod:`model_selection`) that shield the user from data leakage.

    memmapping
    memory map
    memory mapping
        TODO

    missing values
        TODO

    narrative docs
    narrative documentation
        An alias for :ref:`User Guide <user_guide>`, i.e. documentation written
        in ``doc/modules/``.

    ``n_features``
        The number of :term:`features`.

    ``n_outputs``
        The number of :term:`outputs` in the :term:`target`.

    ``n_samples``
        The number of :term:`samples`.

    ``n_targets``
        Synonym for :term:`n_outputs`.

    out-of-core
        TODO

    outputs
        TODO?

    parameter
    parameters
    param
    params
        We mostly use *parameter* to refer to the aspects of an estimator that
        can be specified in its construction. For example, ``max_depth`` and
        ``random_state`` are parameters of :class:`RandomForestClassifier`.
        Parameters to an estimator's constructor are stored as attributes the
        estimator, and conventionally start with an alphabetic character and
        end with an alphanumeric character.  Each estimator's constructor
        parameters are described in the estimator's docstring.

        We do not use parameters in the statistical sense, where parameters are
        values that specify a model and can be estimated from data. What we
        call parameters might be what statisticians call hyperparameters to the
        model: aspects for configuring model structure that are often not
        directly learnt from data.  However, our parameters are also used to
        prescribe modeling operations that do not affect the learnt model, such
        as :term:`n_jobs` for controlling parallelism.

        When talking about the parameters of a :term:`meta-estimator`, we may
        also be including the parameters of the estimators wrapped by the
        meta-estimator.  Ordinarily, these nested parameters are denoted by
        using a double-underscore (``__``) to separate between the
        estimator-as-parameter and its parameter.  Thus
        ``BaggingClassifier(base_estimator=DecisionTreeClassifier(max_depth=3))``
        has a deep parameter ``base_estimator__max_depth`` with value ``3``.

        The list of parameters and their current values can be retrieved from
        an :term:`estimator instance` using its :term:`get_params` method.

        Between construction and fitting, parameters may be modified using
        :term:`set_params`.  To enable this, parameters are not ordinarily
        validated or altered when the estimator is constructed, or when each
        parameter is set. Parameter validation is performed when :term:`fit` is
        called.

        Common parameters are listed :ref:`below <glossary_attributes>`.

    pairwise metric
        TODO

        See precomputed.

    precomputed
        TODO

    rectangular
        Data that can be represented as a matrix with :term:`samples` on the
        first axis and a fixed, finite set of :term:`features` on the second
        is called rectangular.

        This term excludes samples with non-vectorial structure, such as text,
        an image of arbitrary size, a time series of arbitrary length, a set of
        vectors, etc. The purpose of a :term:`vectorizer` is to produce
        rectangular forms of such data.

    sample
    samples
        We usually use this term as a noun to indicate a single feature vector.
        Elsewhere a sample is called an instance, data point, or observation.
        ``n_samples`` indicates the number of samples in a dataset.

    sample property
    sample properties
        TODO

    scikit-learn-contrib
        TODO

    scorer
        TODO
        See :ref:`scoring_parameter`.
        See also :term:`evaluation metric`.

    sparse matrix
        TODO

    target
    targets
        TODO

        Dependent variable or outcome variable.

    unlabeled
    unlabeled data
        TODO

Class APIs and Estimator Types
==============================

.. glossary::

    classifier
        TODO
        Mention that within scikit-learn, all support multi-class
        classification, defaulting to OvR.
        Mention :func:`~base.is_classifier`.

    clusterer
        TODO

    cross validation splitter
    CV splitter
        TODO

    estimator
        TODO

        The core functionality of some estimators may also be available as a
        :term:`function`.

    feature extractor
        A :term:`tranformer` which takes input where each sample is not
        represented as an :term:`array-like` object of fixed length, and
        produces an `array-like` object of :term:`features` for each sample
        (and thus a 2-dimensional array-like for a set of samples).  In other
        words, it (lossily) maps a non-rectangular data representation into
        :term:`rectangular` data.

    meta-estimator
        TODO

        Mention duck typing. Mention that duck typing of methods only works
        after fitting. Mention lenient validation. ?Mention sample props.

    outlier detector
        TODO

    predictor
        An :term:`estimator` which provides :term:`predict`.
        This encompasses :term:`classifier`, :term:`regressor`,
        :term:`outlier detector` and sometimes :term:`clusterer` (at least when
        they are inductive).  In scikit-learn, if an estimator is not a
        predictor, it is usually a :term:`transformer`.

    regressor
        TODO
        Mention :func:`~base.is_regressor`.

    transformer
        TODO

    vectorizer
        See :term:`feature extractor`.

There are further APIs specifically related to a small family of estimators,
such as:

* :class:`neighbors.DistanceMetric`
* :class:`gaussian_process.kernels.Kernel`
* ``tree.Criterion``

.. _glossary_target_types:

Target Types
============

.. glossary::

    binary
        A classification problem consisting of two classes.  A binary target
        may represented as for a :term:`multiclass` problem but with only two
        labels.  A binary decision function is represented as a 1d array.

        Note that a dataset sampled from a multiclass ``y`` or a continuous
        ``y`` may appear to be binary.

        :func:`~utils.multiclass.type_of_target` will return 'binary' for
        binary input, or a similar array with only a single class present.

    continuous
        TODO

    multiclass
        A classification problem consisting of more than two classes.  A
        multiclass target may be represented as a 1-dimensional array of
        strings or integers. A 2d column vector of integers (i.e. a
        single output is also accepted.

        We may also support other orderable, hashable objects as class labels.

        For semi-supervised classification, :term:`unlabeled` samples should
        have the special label -1 in ``y``.

        Within sckit-learn, all estimators supporting binary classification
        also support multiclass classification, using One-vs-Rest by default.

        A :class:`preprocessing.LabelEncoder` helps to canonicalize multiclass
        targets as integers.

        :func:`~utils.multiclass.type_of_target` will return 'multiclass' (or
        'binary' in the degenerate case) for multiclass input.

    multilabel
        A multioutput target where each output is :term:`binary`.  This may be
        represented as a 2d (dense) array or sparse matrix of integers, such
        that each column is a separate binary target, where positive labels are
        indicated with 1 and negative labels are usually -1 or 0.

        Semantically, a multilabel target can be thought of as a set of labels
        for each sample.  While not used internally,
        :class:`preprocessing.MultiLabelBinarizer` is provided as a utility to
        convert from a list of sets representation to a 2d array or sparse
        matrix.

        :func:`~utils.multiclass.type_of_target` will return
        'multilabel-indicator' for multilabel input, whether sparse or dense.

    multioutput continuous
        TODO

    multioutput multiclass
        A classification problem .

        TODO

Methods
=======

.. glossary::

    ``decision_function``

        In a fitted :term:`classifier` or :term:`outlier detector`, predicts a
        "soft" score for each sample in relation to each class, rather than the
        "hard" categorical prediction produced by :term:`predict`.

        Output conventions:

        binary classification
            A 1-dimensional array, where values strictly greater than zero
            indicate the positive class (i.e. the last class in
            :term:`classes_`).
        multiclass classification
            A 2-dimensional array, where the row-wise arg-maximum is the
            predicted class.  Columns are ordered according to
            :term:`classes_`.
        multilabel classification
            Scikit-learn is inconsistent in its representation of multilabel
            decision functions.  Some represent it like multioutput multiclass,
            i.e. a list of 2d arrays, each with two columns. Others represent
            it with a single 2d array, whose columns correspond to the
            individual binary classification decisions. The latter
            representation is ambiguously identical to the multiclass
            classification format, though its semantics differ: it should be
            interpreted, like in the binary case, by thresholding at 0.

            ..
            see https://gist.github.com/jnothman/4807b1b0266613c20ba4d1f88d0f8cf5
        multioutput classification
            A list of 2d arrays, corresponding to each multiclass decision
            function.
        outlier detection
            A 1-dimensional array, where a value greater than or equal to zero
            (TODO: check equality case) indicates an inlier.

    ``get_feature_names``
        TODO

    ``get_n_splits``
        TODO

    ``get_params``
        TODO

    ``fit_predict``
        TODO

        See :term:`labels_`

    ``fit_transform``
        TODO

        Syntactic sugar.
        Efficiency.
        ``transform`` may not be available.
        ``fit_transform`` can be different, as in stacking.

        Ordinarily should not be applied to the entirety of a dataset, only the
        training data, to avoid :term:`leakage`.

    ``fit``
        The ``fit`` method is provided on every estimator. It usually takes some
        :term:`samples` ``X``, :term:`targets` ``y`` if the model is supervised,
        and potentially other :term:`sample properties` such as
        :term:`sample_weight`.  It should:

        * clear any prior :term:`attributes` stored on the estimator, unless
          :term:`warm_start` is used;
        * validate and interpret any :term:`parameters`, ideally raising an
          error if invalid;
        * validate the input data;
        * estimate and store model attributes from the estimated parameters and
          provided data; and
        * return the now :term:`fitted` estimator to facilitate method
          chaining.

        :ref:`glossary_target_types` describes possible formats for ``y``.

    ``partial_fit``
        Facilitates fitting an estimator in an online fashion.  Unlike ``fit``,
        repeatedly calling ``partial_fit`` does not clear the model, but
        updates it with respect to the data provided. The portion of data
        provided to ``partial_fit`` may be called a mini-batch.
        Each mini-batch must be of consistent shape, etc.

        ``partial_fit`` may also be used for :term:`out-of-core` learning,
        although limited to the case where learning can be performed online,
        i.e. the model is usable after each ``partial_fit`` and there is no
        separate processing needed to finalize the model.
        :class:`cluster.Birch` introduces the convention that calling
        ``partial_fit(X)`` will produce a model that is not finalized, but the
        model can be finalized by calling ``partial_fit()`` i.e. without
        passing a further mini-batch.

        Generally, estimator parameters should not be modified between calls
        to ``partial_fit``, although ``partial_fit`` should validate them
        as well as the new mini-batch of data.

        Like ``fit``, ``partial_fit`` should return the estimator object.

        To clear the model, a new estimator should be constructed, for instance
        with :func:`base.clone`.

    ``predict``
        Makes a prediction for each sample. In a :term:`classifier` or
        :term:`regressor`, this prediction is in the same target space used in
        fitting (e.g. one of {'red', 'amber', 'green'} if the `y` in fitting
        consisted of these strings).  In a :term:`clusterer` or :term:`outlier
        detector` the prediction is an integer.

        TODO

        Return type is array ...

        classifier
            TODO

        clusterer
            TODO
            -1 in DBSCAN

        outlier detector
            TODO

        regressor

        Mention ``return_std``

    ``predict_log_proba``
        TODO

    ``predict_proba``
        TODO

        Output conventions are like those for ``decision_function`` except
        in the :term:`binary` case.

    ``score``
        TODO

    ``score_samples``
        TODO

    ``set_params``
        TODO

    ``split``
        TODO

.. _glossary_parameters:

Parameters
==========

These common parameter names, specifically used in estimator construction
(see concept :term:`parameter`) sometimes also appear as function and
non-estimator parameters with similar semantics.

.. glossary::

    ``affinity``
        TODO
        See also :term:`kernel`

        XXX: hierarchical clustering uses ``affinity`` for a distance metric.

    ``class_weight``
        Used to specify sample weights when fitting classifiers as a function
        of the :term:`target` class.  Where the :term:`sample_weight`
        :term:`sample property` is also supported and given, it is multiplied
        by the ``class_weight`` contribution. Similarly, where ``class_weight``
        is used in a :term:`multioutput` (including :term:`multilabel`) tasks,
        the weights are multiplied across outputs (i.e. columns of ``y``).

        By default all samples have equal weight such that classes are
        effectively weighted by their their prevalence in the training data.
        This could be achieved explicitly with ``class_weight={label1: 1,
        label2: 1, ...}`` for all class labels.

        More generally, ``class_weight`` is specified as a dict mapping class
        labels to weights (``{class_label: weight}``), such that each sample
        of the named class is given that weight.

        ``class_weight='balanced'`` can be used to give all classes
        equal weight by giving each sample a weight inversely related
        to its class's prevalence in the training data:
        ``n_samples / (n_classes * np.bincount(y))``.

        For multioutput classification, a list of dicts is used to specify
        weights for each output. For example, for four-class multilabel
        classification weights should be ``[{0: 1, 1: 1}, {0: 1, 1: 5}, {0: 1,
        1: 1}, {0: 1, 1: 1}]`` instead of ``[{1:1}, {2:5}, {3:1}, {4:1}]``.

        The ``class_weight`` parameter is validated and interpreted with
        :func:`utils.compute_class_weight`.

    ``cv``
        Determines a cross validation splitting strategy, as used in
        cross-validation based routines. ``cv`` is also available in estimators
        such as :class:`multioutput.ClassifierChain` which use the predictions
        of one estimator as training data for another, to not overfit the
        training supervision.

        Possible inputs for ``cv`` are usually:

        - An integer, specifying the number of folds in K-fold cross
          validation. K-fold will be stratified over classes if the estimator
          is a classifier (determined by :func:`base.is_classifier`) and the
          :term:`targets` may represent a binary or multiclass (but not
          multioutput) classification problem (determined by
          :func:`utils.multiclass.type_of_target`).
        - A :term:`cross validation splitter` instance. Refer to the
          :ref:`User Guide <cross_validation>` for splitters available
          within Scikit-learn.
        - An iterable yielding train/test splits.

        With some exceptions (especially where not using cross validation at
        all is an option), the default is 3-fold.

        ``cv`` values are validated and interpreted with :func:`utils.check_cv`.

    ``kernel``
        TODO
        See also :term:`affinity`

    ``max_iter``
        For estimators involving iterative optimization, this determines the
        maximum number of iterations to be performed in :term:`fit`.  If
        ``max_iter`` iterations are run without convergence, a
        :class:`exceptions.ConvergenceWarning` should be raised.

        TODO is this always epochs?

        FIXME perhaps we should have some common tests about the relationship
        between ConvergenceWarning and max_iter.

    ``memory``
        Some estimators make use of :class:`joblib.Memory` to
        store partial solutions during fitting. Thus when ``fit`` is called
        again, those partial solutions have been memoized and can be reused.

        A ``memory`` parameter can be specified as a string with a path to a
        directory, or a :class:`joblib.Memory` instance (or an object with a
        similar interface, i.e. a ``cache`` method) can be used.

        ``memory`` values are validated and interpreted with
        :func:`utils.validation.check_memory`.

    ``metric``
        TODO

    ``n_jobs``
        This is used to specify how many concurrent processes/threads should be
        used for parallelized routines.  Scikit-learn uses one processor for
        its processing by default, although it also makes use of NumPy, which
        may be configured to use a threaded numerical processor library (like
        MKL).

        ``n_jobs`` is an int, specifying the maximum number of concurrently
        running jobs.  If set to -1, all CPUs are used. If 1 is given, no
        parallel computing code is used at all.  For n_jobs below -1, (n_cpus +
        1 + n_jobs) are used. Thus for n_jobs = -2, all CPUs but one are used.

        The use of ``n_jobs``-based parallelism in estimators varies:

        * Most often parallelism happens in :term:`fitting <fit>`, but
          sometimes parallelism happens in prediction (e.g. in random forests).
        * Some parallelism uses a multi-threading backend by default, some
          a multi-processing backend.  It is possible to override the default
          backend by using :func:`sklearn.externals.joblib.parallel.parallel_backend`.
        * Whether parallel processing is helpful at improving runtime depends
          on many factors, and it's usually a good idea to experiment rather
          than assuming that increasing the number of jobs is always a good
          thing.

        Nested uses of ``n_jobs``-based parallelism with the same backend will
        result in an exception.
        So ``GridSearchCV(OneVsRestClassifier(SVC(), n_jobs=2), n_jobs=2)``
        won't work.

        When ``n_jobs`` is not 1, the estimator being parallelized must be
        picklable.  This means, for instance, that lambdas cannot be used
        as estimator parameters.

    ``random_state``
        Whenever randomization is part of a Scikit-learn algorithm, a
        ``random_state`` parameter may be provided to control the random number
        generator used.  Note that the mere presence of ``random_state`` doesn't
        mean that randomization is always used, as it may be dependent on
        another parameter, e.g. ``shuffle``, being set.

        ``random_state``'s value may be:

            None (default)
                Use the global random state from :mod:`numpy.random`.

            An integer
                Use a new random number generator seeded by the given integer.
                To make a randomized algorithm deterministic (i.e. running it
                multiple times will produce the same result), an arbitrary
                integer ``random_state`` can be used. However, it may be
                worthwhile checking that your results are stable across a
                number of different distinct random seeds.

            A :class:`numpy.random.RandomState` instance
                Use the provided random state, only affecting other users
                of the same random state instance.

        :func:`utils.check_random_state` is used internally to validate the
        input ``random_state`` and return a :class:`~numpy.random.RandomState`
        instance.

    ``scoring``
        Specifies the score function to be maximized (usually by :ref:`cross
        validation <cross_validation>`), or -- in some cases -- multiple score
        functions to be reported. The score function can be a string accepted
        by :func:`metrics.get_scorer` or a callable :term:`scorer`, not to be
        confused with an :term:`evaluation metric`, as the latter have a more
        diverse API.  ``scoring`` may also be set to None, in which case the
        estimator's ``score`` method is used.  See :ref:`scoring_parameter` in
        the user guide.

        Where multiple metrics can be evaluated, ``scoring`` may be given
        either as a list of unique strings or a dict with names as keys and
        callables as values. Note that this does *not* specify which score
        function is to be maximised, and another parameter such as ``refit``
        may be used for this purpose.

        The ``scoring`` parameter is validated and interpreted using
        :func:`metrics.check_scoring`.

    ``verbose``
        Logging is not handled very consistently in Scikit-learn at present,
        but when it is provided as an option, the ``verbose`` parameter is
        usually available to choose no logging (set to False). Any True value
        should enable some logging, but larger integers (e.g. above 10) may be
        needed for full verbosity.  Verbose logs are usually printed to
        Standard Output.
        Estimators should not produce any output on Standard Output with the
        default ``verbose`` setting.

    ``warm_start``

        When fitting an estimator repeatedly on the same dataset, but for
        multiple parameter values (such as to find the value maximizing
        performance as in :ref:`grid search <grid_search>`), it may be possible
        to reuse aspects of the model learnt from the previous parameter value,
        saving time.  When ``warm_start`` is true, the existing :term:`fitted`
        model :term:`attributes` an are used to initialise the new model
        in a subsequent call to :term:`fit`.

        Note that this is only applicable for some models and some
        parameters, and even some orders of parameter values. For example,
        ``warm_start`` may be used when building random forests to add more
        trees to the forest (increasing ``n_estimators``) but not to reduce
        their number.

        :term:`partial_fit` also retains the model between calls, but differs:
        with ``warm_start`` the parameters change and the data is constant
        across calls to ``fit``; with ``partial_fit``, the mini-batch of data
        changes and model parameters stay fixed.

.. _glossary_attributes:

Attributes
==========

See concept :term:`attribute`.

.. glossary::

    ``classes_``
        TODO

    ``components_``
        TODO

    ``embedding_``
        TODO
        See also :term:`labels_`

    ``n_iter_``
        TODO

    ``feature_importances_``
        TODO

    ``labels_``
        TODO
        See also :term:`embedding_`

.. _glossary_sample_props:

Sample properties
=================

See concept :term:`sample property`.

.. glossary::

    ``groups``
        Used in cross validation routines to identify samples which are
        correlated.  Each value is an identifier such that, in a supporting
        :term:`CV splitter`, samples from some ``groups`` value may not
        appear in both a training set and its corresponding test set.
        See :ref:`group_cv`.

    ``sample_weight``

        A relative weight for each sample.  Intuitively, if all weights are
        integers, a weighted model or score should be equivalent to that
        calculated when repeating the sample the number of times specified in
        the weight.  Weights may be specified as floats, so that
        sample weights are usually equivalent up to a constant positive
        scaling factor.

        FIXME  Is this interpretation always the case in practice? We have no
        common tests.

        This is not entirely the case where other parameters of the model
        consider the number of samples in a region, as with ``min_samples`` in
        :class:`cluster.DBSCAN`.  In this case, a count of samples becomes
        to a sum of their weights.

        In classification, sample weights can also be specified as a function
        of class with the :term:`class_weight` estimator :term:`parameter`.
