import math
from locator.main import estimate_position, Scan


def test_estimate_position_two_anchors():
    # Two anchors at (0,0,0) and (10,0,0); stronger RSSI at A should pull position towards A
    anchors = {"A": (0.0, 0.0, 0.0), "B": (10.0, 0.0, 0.0)}
    scans = [
        Scan(ts=None, anchor_id="A", uid="W", rssi=-50.0, battery=None),
        Scan(ts=None, anchor_id="B", uid="W", rssi=-60.0, battery=None),
    ]
    x, y, z, q = estimate_position(scans, anchors, tx_power_ref=-59.0, path_loss_exponent=2.0, k=2)
    # Position should lie between 0 and 10 and closer to 0 due to stronger RSSI
    assert 0.0 <= x <= 10.0
    assert x < 5.0
    assert y == 0.0
    assert z == 0.0
    assert 0.0 < q <= 1.0


def test_estimate_position_no_scans():
    anchors = {"A": (0.0, 0.0, 0.0)}
    x, y, z, q = estimate_position([], anchors, -59.0, 2.0, 3)
    # With no scans, return zeros
    assert (x, y, z, q) == (0.0, 0.0, 0.0, 0.0)