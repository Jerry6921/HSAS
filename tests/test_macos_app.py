from pathlib import Path


def test_native_app_supports_javascript_confirmation_panels() -> None:
    source = (
        Path(__file__).parents[1] / "packaging" / "macos" / "HIQSApp.swift"
    ).read_text(encoding="utf-8")

    assert "WKUIDelegate" in source
    assert "view.uiDelegate = self" in source
    assert "runJavaScriptConfirmPanelWithMessage" in source
    assert "completionHandler(response == .alertFirstButtonReturn)" in source
