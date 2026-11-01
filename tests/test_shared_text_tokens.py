import pytest

from hsas.application.text_tokens import tokenize


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("中文测试", ["中文", "文测", "测试"]),
        ("BIO 2026", ["bio", "2026"]),
        ("word word", ["word", "word"]),
        ("", []),
        ("TeSt TEST", ["test", "test"]),
    ],
)
def test_shared_tokenize_preserves_historical_tokens(text, expected):
    assert tokenize(text) == expected


def test_shared_tokenize_unique_keeps_first_occurrence_order():
    assert tokenize("中文测试 中文 test TEST", unique=True) == [
        "中文",
        "文测",
        "测试",
        "test",
    ]

