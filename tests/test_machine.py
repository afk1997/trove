import platform
import machine


def test_probe_returns_required_keys():
    info = machine.probe()
    assert isinstance(info, dict)
    for key in ("os_name", "os_version", "arch", "cpu_cores",
                "ram_gb", "free_disk_gb", "gpu"):
        assert key in info, f"missing key: {key}"


def test_probe_arch_is_a_string():
    assert isinstance(machine.probe()["arch"], str)


def test_probe_cpu_cores_is_positive():
    assert machine.probe()["cpu_cores"] >= 1


def test_probe_ram_gb_is_positive():
    assert machine.probe()["ram_gb"] >= 1


def test_probe_free_disk_gb_is_non_negative():
    assert machine.probe()["free_disk_gb"] >= 0


def test_probe_gpu_describes_acceleration(monkeypatch):
    """gpu should be one of: 'metal', 'cuda', 'cpu' depending on the platform."""
    info = machine.probe()
    assert info["gpu"] in ("metal", "cuda", "cpu")


def test_speed_estimate_returns_realtime_factor():
    """machine.speed_estimate(model_name) returns a float — multiplier of realtime
    transcription speed for the given model on this machine.
    """
    rtf = machine.speed_estimate("ggml-base.bin")
    assert isinstance(rtf, float)
    assert rtf > 0


def test_speed_estimate_smaller_model_is_faster():
    """tiny should run faster than medium on any tier."""
    tiny_rtf = machine.speed_estimate("ggml-tiny.bin")
    medium_rtf = machine.speed_estimate("ggml-medium.bin")
    assert tiny_rtf > medium_rtf
