from gpstrack.usb_discovery import find_usb_gateway

HEADER = "Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT"


def write_route_table(tmp_path, lines):
    path = tmp_path / "route"
    path.write_text(HEADER + "\n" + "\n".join(lines) + "\n")
    return str(path)


def test_finds_gateway_on_usb_like_interface(tmp_path):
    # 8934280A little-endian -> 10.40.52.137
    path = write_route_table(
        tmp_path,
        [
            "enx6653e710bbe9\t00000000\t8934280A\t0003\t0\t0\t100\t00000000\t0\t0\t0",
            "wlp58s0\t00000000\t0158A8C0\t0003\t0\t0\t600\t00000000\t0\t0\t0",
        ],
    )

    assert find_usb_gateway(route_table_path=path) == "10.40.52.137"


def test_ignores_non_default_routes(tmp_path):
    path = write_route_table(
        tmp_path,
        [
            "enx6653e710bbe9\t0034280A\t00000000\t0001\t0\t0\t100\t00FFFFFF\t0\t0\t0",
        ],
    )

    assert find_usb_gateway(route_table_path=path) is None


def test_ignores_default_route_on_non_usb_interface(tmp_path):
    path = write_route_table(
        tmp_path,
        [
            "wlp58s0\t00000000\t0158A8C0\t0003\t0\t0\t600\t00000000\t0\t0\t0",
        ],
    )

    assert find_usb_gateway(route_table_path=path) is None


def test_missing_route_table_returns_none(tmp_path):
    assert find_usb_gateway(route_table_path=str(tmp_path / "does-not-exist")) is None
