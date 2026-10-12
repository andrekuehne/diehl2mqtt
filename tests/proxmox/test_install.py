"""Host-installer checks without accessing a Proxmox node or production secrets."""
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("installer", ROOT / "scripts/install-proxmox.py")
app = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(app)


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.usb = {"port": "1-2", "vendor": "0bda", "product": "2838", "serial": "test",
                    "path": "/dev/bus/usb/001/003"}
        self.saved = {"ctid": 123, "marker": "d2m-test", "usb": self.usb}
        self.config = ("unprivileged: 1\ntags: diehl2mqtt;d2m-test\n"
                       "dev0: /dev/bus/usb/001/003,mode=0600,uid=0,gid=0\n")

    def fake_run(self, running=True, healthy=True):
        calls = []
        def run(*args, **kwargs):
            calls.append(args)
            output = "status: running\n" if running else "status: stopped\n"
            code = 0 if args[1] != "exec" or healthy else 1
            return subprocess.CompletedProcess(args, code, output, "")
        return run, calls

    def test_resource_limits_and_creation_options(self):
        for validator, invalid in ((app.memory_value, ('0', '255', '65537', 'bad')),
                                   (app.disk_value, ('0', '1', '1025', 'bad'))):
            for value in invalid:
                with self.assertRaises(ValueError):
                    validator(value)
        settings = dict(ctid=123, hostname='reader', storage='local-lvm',
                        bridge='vmbr0', address='dhcp', gateway='', vlan='',
                        marker='d2m-test', memory=1024, disk=8)
        command = app.create_command(settings, '/tmp/image.tar')
        self.assertEqual(command[command.index('--memory') + 1], '1024')
        self.assertEqual(command[command.index('--rootfs') + 1], 'local-lvm:8')

    def test_bootstrap_keeps_recovery_separate_and_secrets_untouched(self):
        for name in ('opt/watermeter/watermeter', 'opt/venv/bin', 'usr/share/watermeter',
                     'usr/local/bin', 'etc/diehl2mqtt/secrets'):
            (self.root / name).mkdir(parents=True, exist_ok=True)
        for filename in ('__init__.py', 'lxc.py', 'update.py', 'health.py'):
            (self.root / 'opt/watermeter/watermeter' / filename).write_text('# test')
        for filename in ('wmbusmeters', 'rtl_wmbus', 'entrypoint.sh', 'healthcheck.sh', 'update'):
            (self.root / 'usr/local/bin' / filename).write_text('test')
        secret = self.root / 'etc/diehl2mqtt/secrets/meter_aes_key'
        secret.write_text('synthetic-only')
        secret.chmod(0o600)
        with patch.object(app.os, 'chown'):
            app.bootstrap_updates(self.root, 'v0.4.0', 'test-image', (100000, 100000))
        base = self.root / 'opt/diehl2mqtt'
        self.assertEqual(os.readlink(base / 'current'), 'releases/v0.4.0-initial')
        self.assertTrue((base / 'launcher/watermeter/lxc.py').is_file())
        self.assertTrue((base / 'releases/v0.4.0-initial/watermeter/watermeter/lxc.py').is_file())
        self.assertEqual(secret.read_text(), 'synthetic-only')
        self.assertEqual(secret.stat().st_mode & 0o777, 0o600)
        config = self.root / 'etc/diehl2mqtt/install.json'
        self.assertEqual(config.stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(config.read_text())['kind'], 'diehl2mqtt-lxc')
        with self.assertRaises(app.InstallError):
            app.bootstrap_updates(self.root, 'v0.4.0', 'test-image', (100000, 100000))

    def test_existing_vm_id_is_refused_cluster_wide(self):
        with patch.object(app, "command_json", return_value=[{"vmid": 123, "type": "qemu", "node": "other"}]):
            with self.assertRaises(app.InstallError):
                app.check_unused(123)

    def test_invalid_ct_ids_are_refused(self):
        for value in ("0", "99", "1000000000", "bad"):
            with self.assertRaises(ValueError):
                app.ctid_value(value)

    def test_pct_child_creates_traversable_directories_without_changing_parent_umask(self):
        executable = self.root / "pct"
        executable.write_text(f"#!{sys.executable}\nimport os, sys\nos.makedirs(sys.argv[1])\n")
        executable.chmod(0o700)
        old_umask = os.umask(0o077)
        try:
            app.run(executable, self.root / "guest/rootfs")
            self.assertEqual((self.root / "guest").stat().st_mode & 0o777, 0o755)
            self.assertEqual((self.root / "guest/rootfs").stat().st_mode & 0o777, 0o755)
            private = self.root / "monitor.json"
            private.write_text("{}")
            self.assertEqual(private.stat().st_mode & 0o777, 0o600)
            app.run(sys.executable, "-c", "from pathlib import Path; import sys; Path(sys.argv[1]).mkdir()",
                    self.root / "other-child")
            self.assertEqual((self.root / "other-child").stat().st_mode & 0o777, 0o700)
        finally:
            os.umask(old_umask)

    def test_create_is_unprivileged_stopped_and_not_nested(self):
        settings = {"ctid": 123, "hostname": "reader", "storage": "local-lvm", "bridge": "vmbr0",
                    "address": "192.0.2.10/24", "gateway": "192.0.2.1", "vlan": "20", "marker": "d2m-test"}
        command = app.create_command(settings, "/tmp/public-image.tar")
        self.assertEqual(command[command.index("--unprivileged") + 1], "1")
        self.assertEqual(command[command.index("--start") + 1], "0")
        self.assertNotIn("--features", command)
        self.assertIn("host-managed=1", command[command.index("--net0") + 1])
        self.assertIn("gw=192.0.2.1,tag=20", command[command.index("--net0") + 1])

    def test_image_environment_kept_and_overrides_not_duplicated(self):
        old = "lxc.environment.runtime: PATH=/opt/venv/bin:/usr/bin\n" \
              "lxc.environment.runtime: METER_ID=12345678\n" \
              "lxc.environment.runtime: WMBUS_FAST_MATH=false\n" \
              "lxc.environment.runtime: WMBUS_ALGORITHM=both\n" \
              "lxc.environment.runtime: PYTHONPATH=/opt/watermeter\n"
        result = app.configure_text(old, {"METER_ID": "00123456", "METER_AES_KEY_FILE": "/etc/diehl2mqtt/secrets/meter_aes_key",
                                          "WMBUS_FAST_MATH": "true", "WMBUS_ALGORITHM": "time2"})
        self.assertEqual(result.count("METER_ID="), 1)
        self.assertIn("METER_ID=00123456", result)
        self.assertEqual(result.count("WMBUS_FAST_MATH="), 1)
        self.assertEqual(result.count("WMBUS_ALGORITHM="), 1)
        self.assertIn("WMBUS_FAST_MATH=true", result)
        self.assertIn("WMBUS_ALGORITHM=time2", result)
        self.assertIn("PATH=/opt/venv/bin:/usr/bin", result)
        self.assertIn("tmpfs run/watermeter tmpfs nosuid,nodev,mode=0700,create=dir", result)
        self.assertNotIn("METER_AES_KEY=", result)
        with self.assertRaises(app.InstallError):
            app.configure_text(old, {"METER_ID": "12345678\nlxc.apparmor.profile: unconfined"})

    def test_secret_permissions_and_no_overwrite_or_symlink(self):
        owner = (os.getuid(), os.getgid())
        app.write_secret(self.root, "meter_aes_key", "00112233445566778899aabbccddeeff", owner)
        directory = self.root / "etc/diehl2mqtt/secrets"
        self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
        self.assertEqual((directory / "meter_aes_key").stat().st_mode & 0o777, 0o600)
        with self.assertRaises(FileExistsError):
            app.write_secret(self.root, "meter_aes_key", "other", owner)
        (directory / "mqtt_password").symlink_to(self.root / "outside")
        with self.assertRaises(FileExistsError):
            app.write_secret(self.root, "mqtt_password", "public-test-password", owner)
        self.assertFalse((self.root / "outside").exists())

    def test_privileged_and_unsafe_root_mapping_refused(self):
        self.assertEqual(app.mapped_root("unprivileged: 1\n"), (100000, 100000))
        self.assertEqual(app.mapped_root("unprivileged: 1\nlxc.idmap: u 0 200000 65536\n"), (200000, 100000))
        for config in ("unprivileged: 0\n", "unprivileged: 1\nlxc.idmap: u 0 0 1\n"):
            with self.assertRaises(app.InstallError):
                app.mapped_root(config)

    def test_reused_ct_id_is_never_managed(self):
        with patch.object(app, "CONFIG_DIR", self.root), patch.object(app, "PVE_CONFIG", self.root):
            (self.root / "123.json").write_text(json.dumps(self.saved))
            (self.root / "123.conf").write_text(self.config.replace("d2m-test", "other-owner"))
            with self.assertRaises(app.InstallError):
                app.managed_config(123)

    def test_usb_address_discovery_and_identity(self):
        port = self.root / "1-2"
        port.mkdir()
        for name, value in {"idVendor": "0bda", "idProduct": "2838", "serial": "test", "busnum": "1", "devnum": "27"}.items():
            (port / name).write_text(value)
        with patch.object(app, "USB_SYSFS", self.root):
            current = app.device("1-2")
            self.assertEqual(current["path"], "/dev/bus/usb/001/027")
            self.assertTrue(app.same_device(self.usb, current))
            self.assertFalse(app.same_device(self.usb, dict(current, serial="different")))

    def test_missing_or_replaced_usb_stops_without_starting(self):
        for current in (None, dict(self.usb, serial="different")):
            run, calls = self.fake_run()
            with patch.object(app, "device", return_value=current), patch.object(app, "run", side_effect=run):
                state = app.reconcile(123, self.saved, self.config, {}, 100)
            self.assertIn("Waiting", state["message"])
            self.assertEqual([c[1] for c in calls], ["status", "shutdown"])

    def test_replug_rebinds_new_address_before_starting(self):
        run, calls = self.fake_run()
        current = dict(self.usb, path="/dev/bus/usb/001/027")
        with patch.object(app, "device", return_value=current), patch.object(app, "run", side_effect=run), patch.object(app, "detach_dvb"):
            state = app.reconcile(123, self.saved, self.config, {}, 100)
        self.assertEqual([c[1] for c in calls], ["status", "shutdown", "set", "start"])
        self.assertIn("path=/dev/bus/usb/001/027,uid=0,gid=0,mode=0600", calls[2])
        self.assertEqual(state["started"], 100)

    def test_running_healthy_reader_is_not_restarted(self):
        run, calls = self.fake_run()
        with patch.object(app, "device", return_value=self.usb), patch.object(app, "run", side_effect=run), patch.object(app, "detach_dvb"):
            app.reconcile(123, self.saved, self.config, {"started": 1}, 100)
        self.assertEqual([c[1] for c in calls], ["status", "exec"])
        self.assertEqual(list(calls[1]), app.health_command(123))
        self.assertIn("/opt/venv/bin/python", calls[1])
        self.assertIn("PYTHONPATH=/opt/watermeter", calls[1])

    def test_health_grace_period_then_failure_restarts(self):
        run, calls = self.fake_run(healthy=False)
        with patch.object(app, "device", return_value=self.usb), patch.object(app, "run", side_effect=run), patch.object(app, "detach_dvb"):
            app.reconcile(123, self.saved, self.config, {"started": 90}, 100)
            self.assertEqual([c[1] for c in calls], ["status"])
            calls.clear()
            app.reconcile(123, self.saved, self.config, {"started": 1}, 100)
        self.assertEqual([c[1] for c in calls], ["status", "exec", "shutdown", "start"])

    def test_only_selected_dvb_interface_is_unbound(self):
        driver = self.root / "drivers/dvb_usb_rtl28xxu"
        driver.mkdir(parents=True)
        (driver / "unbind").touch()
        interface = self.root / "1-2:1.0"
        interface.mkdir()
        (interface / "driver").symlink_to(driver)
        with patch.object(app, "USB_SYSFS", self.root):
            app.detach_dvb(self.usb)
        self.assertEqual((driver / "unbind").read_text(), "1-2:1.0\n")

    def test_timed_out_health_check_restarts(self):
        run, calls = self.fake_run()
        def run_timeout(*args, **kwargs):
            if args[1] == "exec":
                calls.append(args)
                raise subprocess.TimeoutExpired(args, 10)
            return run(*args, **kwargs)
        with patch.object(app, "device", return_value=self.usb), patch.object(app, "run", side_effect=run_timeout), patch.object(app, "detach_dvb"):
            app.reconcile(123, self.saved, self.config, {"started": 1}, 100)
        self.assertEqual([c[1] for c in calls], ["status", "exec", "shutdown", "start"])

    def test_other_managed_reader_must_be_disabled_for_replacement(self):
        (self.root / "123.json").write_text(json.dumps(self.saved))
        with patch.object(app, "CONFIG_DIR", self.root), patch.object(app, "run", return_value=subprocess.CompletedProcess([], 0)):
            with self.assertRaises(app.InstallError):
                app.check_exclusive(self.usb)
        with patch.object(app, "CONFIG_DIR", self.root), patch.object(app, "run", return_value=subprocess.CompletedProcess([], 1)):
            app.check_exclusive(self.usb)

    def test_secrets_never_enter_creation_commands(self):
        settings = {"ctid": 123, "hostname": "reader", "storage": "local-lvm", "bridge": "vmbr0",
                    "address": "dhcp", "gateway": "", "vlan": "", "marker": "d2m-test",
                    "env": {"METER_ID": "00123456", "METER_AES_KEY_FILE": "/etc/diehl2mqtt/secrets/meter_aes_key"}}
        command = " ".join(app.create_command(settings, "/tmp/public-image.tar"))
        self.assertNotIn("METER_AES_KEY=", command)
        self.assertNotIn("MQTT_PASSWORD=", command)
        self.assertNotIn("00123456", command)

    def test_release_checksum_required(self):
        image = b"ghcr.io/andrekuehne/diehl2mqtt@sha256:" + b"a" * 64 + b"\n"
        checksum = app.hashlib.sha256(image).hexdigest().encode() + b"  image.txt\n"
        with patch.object(app.urllib.request, "urlopen", side_effect=[io.BytesIO(image), io.BytesIO(checksum)]):
            self.assertEqual(app.release_image("v0.2.0"), image.decode().strip())
        with patch.object(app.urllib.request, "urlopen", side_effect=[io.BytesIO(image), io.BytesIO(b"wrong  image.txt\n")]):
            with self.assertRaises(app.InstallError):
                app.release_image("v0.2.0")

    def test_dry_run_never_executes_installation(self):
        with patch.object(app, "preflight"), patch.object(app, "collect_settings", return_value={}), \
                patch.object(app, "show_plan"), patch.object(app, "execute_install") as execute, \
                patch.object(app.os, "umask"), patch.object(app.sys, "argv", ["installer", "--dry-run"]):
            app.main()
        execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
