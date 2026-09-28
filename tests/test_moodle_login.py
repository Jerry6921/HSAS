from hsas.infrastructure.moodle.gateway import _is_moodle_login_url
from hsas.infrastructure.moodle.settings import HKU_PORTAL_CAS_LOGIN_URL


def test_moodle_login_detection_ignores_cas_query_parameters() -> None:
    assert _is_moodle_login_url(
        "https://moodle.hku.hk/login/index.php", HKU_PORTAL_CAS_LOGIN_URL
    )
    assert _is_moodle_login_url(
        "https://moodle.hku.hk/login/index.php?authCAS=CAS",
        HKU_PORTAL_CAS_LOGIN_URL,
    )
    assert not _is_moodle_login_url(
        "https://moodle.hku.hk/my/", HKU_PORTAL_CAS_LOGIN_URL
    )
