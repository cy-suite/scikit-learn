"""
Test the CountVectorizer feature extractor
"""

from sklearn.utils.testing import assert_equal

from sklearn.feature_extraction.text import CountVectorizer

JUNK = (
    "aa aa aa aa aaa aaa aaaa",
)


def test_token_processor():
    # with token_processor
    poor_mans_stemmer = lambda tok: tok[:3]

    word_vect = CountVectorizer(min_df=0.0, max_df=1.0, analyzer="word",
                                token_processor=poor_mans_stemmer)
    vectorized = word_vect.fit_transform(JUNK)

    feature_names = word_vect.get_feature_names()
    assert_equal(set(feature_names), set(['aa', 'aaa']))

    counts = vectorized.toarray()[0]
    assert_equal(counts[word_vect.vocabulary_['aa']], 4)
    assert_equal(counts[word_vect.vocabulary_['aaa']], 3)

    # without token_processor
    word_vect = CountVectorizer(min_df=0.0, max_df=1.0, analyzer="word")
    vectorized = word_vect.fit_transform(JUNK)

    feature_names = word_vect.get_feature_names()
    assert_equal(set(feature_names), set(['aa', 'aaa', 'aaaa']))

    counts = vectorized.toarray()[0]
    assert_equal(counts[word_vect.vocabulary_['aa']], 4)
    assert_equal(counts[word_vect.vocabulary_['aaa']], 2)
    assert_equal(counts[word_vect.vocabulary_['aaaa']], 1)


def test_token_processor_filter_unwanted_tokens():
    # with token_processor
    def filter_short(tok):
        if len(tok) < 3:
            return None
        return tok

    word_vect = CountVectorizer(
        min_df=0.0, max_df=1.0, analyzer="word", token_processor=filter_short)
    vectorized = word_vect.fit_transform(JUNK)

    feature_names = word_vect.get_feature_names()
    assert_equal(set(feature_names), set(['aaa', 'aaaa']))

    counts = vectorized.toarray()[0]
    assert_equal(counts[word_vect.vocabulary_['aaa']], 2)
    assert_equal(counts[word_vect.vocabulary_['aaaa']], 1)
