import json
import shlex

import pytest

from custom_components.aqara_presence_lab.api.errors import (
    AqaraError,
    InvalidResponse,
    ResponseTooLarge,
)
from custom_components.aqara_presence_lab.api.importers import (
    HOST,
    PATH,
    allowed_url,
    import_curl,
    import_har,
    import_package,
    request_paths,
    strict_json,
)
from tests.transport_helpers import capture


def curl_text():
    item, _ = capture()
    return (
        "curl "
        + shlex.quote(f"https://{HOST}{PATH}")
        + " "
        + " ".join("-H " + shlex.quote(f"{key}: {value}") for key, value in item.headers.items())
        + " --data-raw "
        + shlex.quote(item.body.decode())
    )


def har_text(extra=False):
    item, _ = capture()
    entry = {
        "request": {
            "url": f"https://{HOST}{PATH}",
            "method": "POST",
            "headers": [{"name": key, "value": value} for key, value in item.headers.items()],
            "postData": {"text": item.body.decode()},
        }
    }
    entries = [
        {
            "request": {
                "url": "https://evil.invalid/x",
                "headers": [{"name": "Authorization", "value": "secret-other"}],
            }
        }
    ]
    entries += [entry, entry] if extra else [entry]
    return json.dumps({"log": {"entries": entries}})


def test_package_roundtrip_exact_bytes_and_no_repr_secrets():
    item, _ = capture()
    result = import_package(json.dumps(item.package()))
    assert result.body == item.body
    assert result.credentials == item.credentials
    rendered = repr(result) + repr(result.credentials) + json.dumps(result.preview())
    for value in ("private-token", "private-user", "private-device", item.headers["sign"]):
        assert value not in rendered


def test_har_selects_only_allowed_endpoint_preserves_body():
    result = import_har(har_text())
    assert result.body == capture()[0].body
    assert not result.wire_exact
    assert "Authorization" not in result.headers
    with pytest.raises(InvalidResponse):
        import_har(har_text(extra=True))
    assert import_har(har_text(extra=True), entry_index=2).body == result.body


def test_curl_is_only_parser_preserves_body():
    assert import_curl(curl_text()).body == capture()[0].body


@pytest.mark.parametrize(
    "suffix",
    [
        " | cat",
        "; touch /tmp/pwn",
        " --proxy http://evil",
        " -k",
        " -L",
        " --output file",
        " --data @file",
        " --data-binary @file",
        " --compressed",
        " --header 'Token: second'",
        " $(touch /tmp/pwn)",
        " `id`",
        " > file",
        " --request GET",
    ],
)
def test_curl_rejects_executable_ambiguous_and_network_flags(suffix):
    with pytest.raises(AqaraError):
        import_curl(curl_text() + suffix)


@pytest.mark.parametrize(
    "url",
    [
        f"http://{HOST}{PATH}",
        f"https://evil.invalid{PATH}",
        f"https://{HOST}.evil.invalid{PATH}",
        f"https://user@{HOST}{PATH}",
        f"https://{HOST}:444{PATH}",
        f"https://{HOST}{PATH}?x=1",
        f"https://{HOST}{PATH}#x",
        f"https://{HOST}/write",
        f"https://{HOST}{PATH}\n",
    ],
)
def test_url_allowlist(url):
    with pytest.raises(InvalidResponse):
        allowed_url(url)


@pytest.mark.parametrize(
    "text",
    [
        '{"a":1,"a":2}',
        '{"a":NaN}',
        '{"a":Infinity}',
        '{"a":1e999}',
        "{}{}",
        "<html>",
        "[1]",
        '{"x":"\\ud800"}',
    ],
)
def test_strict_json_bad_shapes(text):
    with pytest.raises(InvalidResponse):
        strict_json(text)


def test_import_limits_and_bad_encoding():
    with pytest.raises(ResponseTooLarge):
        strict_json(b" " * 101, limit=100)
    package = capture()[0].package()
    package["body_base64"] = "@broken"
    with pytest.raises(InvalidResponse):
        import_package(json.dumps(package))
    package = capture()[0].package()
    package["headers"]["Token"] = "duplicate"
    with pytest.raises(InvalidResponse):
        import_package(json.dumps(package))


@pytest.mark.parametrize("change", ["subscribe", "needparam", "duplicate", "empty", "unknown"])
def test_request_contract(change):
    data = json.loads(capture()[0].body)
    if change == "subscribe":
        data["devices"][0]["traits"][0]["needSubscribe"] = False
    if change == "needparam":
        data["needParam"] = False
    if change == "duplicate":
        data["devices"].append(data["devices"][0])
    if change == "empty":
        data["devices"] = []
    if change == "unknown":
        data["write"] = True
    with pytest.raises(InvalidResponse):
        request_paths(json.dumps(data).encode())


def test_multiline_posix_curl_continuations_preserve_single_quoted_body_bytes():
    item, _ = capture()
    body = json.dumps(json.loads(item.body), ensure_ascii=False, indent=2).encode()
    command = "curl \\\n    " + shlex.quote(f"https://{HOST}{PATH}")
    for key, value in item.headers.items():
        command += " \\\n    -H " + shlex.quote(f"{key}: {value}")
    command += " \\\n    --data-raw " + shlex.quote(body.decode())
    assert import_curl(command).body == body


def test_double_quoted_shell_continuation_decodes_argument_before_g1():
    item, _ = capture()
    # POSIX removes backslash-LF inside double quotes before curl sees the body.
    quoted = (
        '"' + item.body.decode().replace('"', '\\"').replace("needParam", "need\\\nParam") + '"'
    )
    command = curl_text().split(" --data-raw ")[0] + " --data-raw " + quoted
    assert import_curl(command).body == item.body


def test_single_quoted_backslash_newline_is_not_silently_repaired():
    item, _ = capture()
    # This JSON is intentionally invalid. Removing its literal continuation
    # would silently turn it into a different valid, signable request.
    broken = item.body.decode().replace("needParam", "need\\\nParam")
    command = curl_text().split(" --data-raw ")[0] + " --data-raw " + shlex.quote(broken)
    with pytest.raises(InvalidResponse):
        import_curl(command)


@pytest.mark.parametrize(
    ("command_text", "expected"),
    [
        ("curl \\\n value", "curl  value"),
        ("curl 'literal\\\ntext'", "curl 'literal\\\ntext'"),
        ('curl "joined\\\ntext"', 'curl "joinedtext"'),
        ("curl \\\\n value", "curl \\\\n value"),
        ("curl \\' \\\n value", "curl \\'  value"),
        ('curl "escaped\\"quote\\\njoined"', 'curl "escaped\\"quotejoined"'),
        ("curl trailing\\", "curl trailing\\"),
    ],
)
def test_posix_continuation_quote_and_escape_boundaries(command_text, expected):
    from custom_components.aqara_presence_lab.api.importers import _remove_shell_continuations

    assert _remove_shell_continuations(command_text) == expected


def test_multiline_curl_does_not_make_disallowed_flags_or_commands_executable():
    command = curl_text().replace(" -H ", " \\\n -H ")
    for suffix in (
        " \\\n --proxy https://evil.invalid",
        " \\\n | cat",
        " \\\n --data-binary @file",
    ):
        with pytest.raises(AqaraError):
            import_curl(command + suffix)


@pytest.mark.parametrize("backslashes", [1, 2, 3, 4])
def test_continuation_only_with_unescaped_backslash(backslashes):
    from custom_components.aqara_presence_lab.api.importers import _remove_shell_continuations

    command = "curl " + "\\" * backslashes + "\nnext"
    expected = "curl " + "\\" * (backslashes - 1) + "next" if backslashes % 2 else command
    assert _remove_shell_continuations(command) == expected
