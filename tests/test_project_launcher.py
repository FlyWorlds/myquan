from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import start_project as launcher


class ProjectLauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runtime = self.root / "logs"
        self.runtime.mkdir()
        self.patches = [
            patch.object(launcher, "RUNTIME", self.runtime),
            patch.object(launcher, "STATE", self.runtime / "state.json"),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def opts(self, **changes):
        return argparse.Namespace(**dict(dict(port=8765, backend_port=8080, ui_port=3000,
                     timeout=2, no_open=True, no_wechat=False, ui_dev=False), **changes))

    def test_wechat_login_keeps_terminal_streams_and_runs_before_detach(self):
        with patch.object(launcher.sys.stdin, "isatty", return_value=True), \
             patch.object(launcher.sys.stdout, "isatty", return_value=True), \
             patch.object(launcher.subprocess, "run", return_value=Mock(returncode=0)) as run:
            launcher.prepare_wechat_terminal(self.opts(wechat_login=True), ["/python", "--wechat-optional"], {})
        args, kwargs = run.call_args
        self.assertIn("send_test=False, force_login=True", args[0][-1])
        for stream in ("stdin", "stdout", "stderr", "capture_output", "start_new_session"):
            self.assertNotIn(stream, kwargs)

    def test_forced_login_without_terminal_does_not_launch_hidden_qr(self):
        with patch.object(launcher.sys.stdin, "isatty", return_value=False), \
             patch.object(launcher.subprocess, "run") as run:
            with self.assertRaises(launcher.LaunchError):
                launcher.prepare_wechat_terminal(self.opts(wechat_login=True), ["/python"], {})
        run.assert_not_called()

    def test_wechat_disabled_skips_terminal_login(self):
        with patch.object(launcher.subprocess, "run") as run:
            launcher.prepare_wechat_terminal(self.opts(), ["/python", "--no-wechat"], {})
        run.assert_not_called()

    def test_forced_login_enables_wechat_when_prior_service_disabled_it(self):
        with patch.object(launcher, "resolve_python", return_value="/python"):
            command, _ = launcher.python_command(self.opts(no_wechat=None, wechat_login=True),
                {"command": ["/python", "--no-wechat"]})
        self.assertIn("--wechat-optional", command)
        self.assertNotIn("--no-wechat", command)

    def test_background_login_never_waits_for_an_invisible_qr(self):
        from holdingStocks import wechat_notify
        with patch.object(wechat_notify.sys.stdin, "isatty", return_value=False), \
             patch.object(wechat_notify.subprocess, "run") as run:
            ok, detail = wechat_notify.run_weixin_channels_login()
        self.assertFalse(ok)
        self.assertIn("bash start.sh --wechat-login", detail)
        run.assert_not_called()

    def test_unknown_port_is_never_reclaimed(self):
        with patch.object(launcher, "port_open", return_value=True), \
             patch.object(launcher, "service_matches", return_value=False), \
             patch.object(launcher.subprocess, "Popen") as spawn, patch.object(launcher.os, "killpg") as kill:
            with self.assertRaises(launcher.LaunchError):
                launcher.start_service("python",8765,[],self.root,{},lambda _:True,{},[],1)
        spawn.assert_not_called()
        kill.assert_not_called()

    def test_retired_combined_launch_scripts_are_removed(self):
        for filename in ("start_watch.py", "start_watch.sh", "start_watch.ps1"):
            self.assertFalse((launcher.ROOT / "holdingStocks" / filename).exists())

    def test_healthy_existing_service_is_reused_not_adopted(self):
        state, created = {}, []
        with patch.object(launcher,"port_open",return_value=True), \
             patch.object(launcher,"service_matches",return_value=True), \
             patch.object(launcher.subprocess,"Popen") as spawn:
            launcher.start_service("python",8765,[],self.root,{},lambda _:True,state,created,1)
        self.assertEqual(state,{})
        self.assertEqual(created,[])
        spawn.assert_not_called()

    def test_pid_reuse_cannot_stop_another_process(self):
        with patch.object(launcher,"process_birth",return_value="new birth"), \
             patch.object(launcher.os,"killpg") as kill:
            launcher.stop_owned(dict(name="python",pid=999,birth="old birth"))
        kill.assert_not_called()

    def test_stop_without_owned_records_never_kills_external_services(self):
        with patch.object(launcher,"stop_owned") as stop:
            self.assertEqual(launcher.stop(),0)
        stop.assert_not_called()

    def test_stop_order_frontend_python_java_and_preserves_database(self):
        records={name:dict(name=name,pid=i+100,birth="birth") for i,name in enumerate(["java","python","frontend"])}
        launcher.write_state(records)
        with patch.object(launcher,"stop_owned") as stop:
            launcher.stop()
        self.assertEqual([call.args[0]["name"] for call in stop.call_args_list],["frontend","python","java"])
        self.assertEqual(launcher.read_state(),{})

    def test_failed_start_rolls_back_only_services_created_in_this_attempt(self):
        old=dict(name="java",pid=100,birth="birth",port=8080)
        launcher.write_state({"java":old})
        created_record=dict(name="python",pid=101,birth="new birth",port=8765)
        def start_service(name,port,command,cwd,env,probe,state,created,timeout):
            if name=="python":
                created.append(created_record)
                state[name]=created_record
                raise launcher.LaunchError("timeout")
        with patch.object(launcher,"same_process",return_value=False), \
             patch.object(launcher,"resolve_python",return_value="/python"), \
             patch.object(launcher,"prepare_frontend",return_value=(None,None)), \
             patch.object(launcher,"ensure_mysql"), patch.object(launcher,"port_open",return_value=True), \
             patch.object(launcher,"start_service",side_effect=start_service), \
             patch.object(launcher,"get_json",return_value={"revision":1}), \
             patch.object(launcher,"stop_owned") as stop:
            with self.assertRaises(launcher.LaunchError):
                launcher.start(self.opts())
        stop.assert_called_once_with(created_record)
        self.assertEqual(launcher.read_state(),{"java":old})

    def test_uninitialized_account_never_starts_python(self):
        with patch.object(launcher,"resolve_python",return_value="/python"), \
             patch.object(launcher,"prepare_frontend",return_value=(None,None)), \
             patch.object(launcher,"ensure_mysql"), patch.object(launcher,"port_open",return_value=True), \
             patch.object(launcher,"get_json",return_value={"revision":0}), \
             patch.object(launcher,"start_service") as service:
            with self.assertRaises(launcher.LaunchError):
                launcher.start(self.opts())
        self.assertEqual([c.args[0] for c in service.call_args_list],["java"])

    def test_concurrent_operation_is_rejected(self):
        with launcher.operation_lock():
            with self.assertRaises(launcher.LaunchError):
                with launcher.operation_lock():
                    pass

    def test_corrupt_manifest_is_not_used_for_stop(self):
        launcher.STATE.write_text('{"python": 123}')
        with self.assertRaises(launcher.LaunchError):
            launcher.read_state()

    def test_no_database_restart_when_port_is_already_open(self):
        with patch.object(launcher,"port_open",return_value=True), patch.object(launcher.subprocess,"run") as run:
            launcher.ensure_mysql()
        run.assert_not_called()

    def test_invalid_probe_payload_does_not_count_as_ready(self):
        with patch.object(launcher,"get_json",return_value=[]):
            self.assertFalse(launcher.watch_ready(8765))
            self.assertFalse(launcher.backend_ready(8080))
        with patch.object(launcher,"get_json",return_value={"application":"myquan-backend","status":"UP","database":None}):
            self.assertFalse(launcher.backend_ready(8080))

    def test_old_backend_without_quote_storage_cannot_pass_account_preflight(self):
        with patch.object(launcher, "get_json", side_effect=[{"revision": 1}, None]), \
             self.assertRaises(launcher.LaunchError):
            launcher.require_account(8080)
        with patch.object(launcher, "get_json", side_effect=[{"revision": 1}, {}]):
            launcher.require_account(8080)
        with patch.object(launcher, "get_json", side_effect=[{"revision": 1}, ValueError("bad response")]), \
             self.assertRaises(launcher.LaunchError):
            launcher.require_account(8080)

    def test_frontend_freshness_and_missing_dist(self):
        ui=self.root / "holdingStocks/watch-ui"
        ui.mkdir(parents=True)
        (ui / "utils").mkdir()
        source=ui / "utils/value.ts"
        source.write_text("export const value=1")
        with patch.object(launcher,"ROOT",self.root):
            self.assertFalse(launcher.static_frontend_ready())
            (ui / "dist").mkdir()
            index=ui / "dist/index.html"
            index.write_text("<html></html>")
            self.assertTrue(launcher.static_frontend_ready())
            os.utime(source,(index.stat().st_mtime+1,index.stat().st_mtime+1))
            self.assertFalse(launcher.static_frontend_ready())

    def test_owned_service_port_change_requires_stop_first(self):
        launcher.write_state({"python":dict(name="python",pid=100,birth="birth",port=8765)})
        with patch.object(launcher,"same_process",return_value=True), patch.object(launcher,"resolve_python") as resolve:
            with self.assertRaises(launcher.LaunchError):
                launcher.start(self.opts(port=8766))
        resolve.assert_not_called()

    def test_missing_process_identity_cleans_the_new_child(self):
        proc=Mock(pid=1234)
        with patch.object(launcher,"port_open",return_value=False), \
             patch.object(launcher.subprocess,"Popen",return_value=proc), \
             patch.object(launcher,"process_birth",return_value=""), \
             patch.object(launcher,"abort_spawn") as abort:
            with self.assertRaises(launcher.LaunchError):
                launcher.start_service("python",8765,["python"],self.root,{},lambda _:True,{},[],1)
        abort.assert_called_once_with(proc)
        self.assertEqual(launcher.read_state(),{})

    def test_managed_python_does_not_silently_ignore_changed_arguments(self):
        state={"python":dict(name="python",pid=100,birth="birth",port=8765,
                            command=["python","--no-wechat"],settings={})}
        with patch.object(launcher,"same_process",return_value=True), \
             patch.object(launcher,"port_open",return_value=True), \
             patch.object(launcher,"service_matches",return_value=True):
            with self.assertRaises(launcher.LaunchError):
                launcher.start_service("python",8765,["python","--wechat-optional"],self.root,{},lambda _:True,state,[],1)

    def test_java_build_cache_uses_content_not_reproducible_jar_timestamp(self):
        backend=self.root / "backend"
        (backend / "src").mkdir(parents=True)
        (backend / "target").mkdir()
        (backend / "pom.xml").write_text("<project/>")
        source=backend / "src/Main.java"
        source.write_text("class Main {}")
        jar=backend / "target/myquan-backend-0.1.0-SNAPSHOT.jar"
        jar.write_bytes(b"jar")
        os.utime(jar,(318240000,318240000))
        with patch.object(launcher,"ROOT",self.root), patch.dict(os.environ,{"JAVA_HOME":str(self.root)}), \
             patch.object(launcher.shutil,"which",return_value="/java"), \
             patch.object(launcher.subprocess,"run") as build:
            launcher.java_command()
            launcher.java_command()
            self.assertEqual(build.call_count,1)
            source.write_text("class Main {int x;}")
            launcher.java_command()
            self.assertEqual(build.call_count,2)
            jar.write_bytes(b"new external jar")
            launcher.java_command()
            self.assertEqual(build.call_count,3)

    def test_python_dependency_version_mismatch_is_visible_not_auto_upgraded(self):
        python=self.root / "python"
        python.write_text("")
        (self.root / "requirements.txt").write_text("akquant==0.3.22\n")
        result=argparse.Namespace(returncode=0,stdout=b'{"akquant":"0.3.21"}')
        output=io.StringIO()
        with patch.object(launcher,"ROOT",self.root), patch.dict(os.environ,{"MYQUAN_PYTHON":str(python)}), \
             patch.object(launcher.subprocess,"run",return_value=result) as run, contextlib.redirect_stdout(output):
            self.assertEqual(launcher.resolve_python(),str(python))
        self.assertIn("0.3.21",output.getvalue())
        self.assertIn("0.3.22",output.getvalue())
        self.assertEqual(run.call_count,1)

    @contextlib.contextmanager
    def replacement_mocks(self, records):
        launcher.write_state(records)
        with contextlib.ExitStack() as stack:
            mocked = {}
            for name, kwargs in {
                "same_process": {"side_effect": lambda record: bool(record.get("pid"))},
                "port_open": {"return_value": True},
                "service_matches": {"return_value": True},
                "require_service": {}, "require_account": {}, "ensure_mysql": {},
                "java_command": {"return_value": (["java"], {})},
                "resolve_python": {"return_value": "/python"},
                "prepare_frontend": {"return_value": ("npm", {})},
                "frontend_ready": {"return_value": True},
                "stop_owned": {"side_effect": lambda record: record.pop("pid", None)},
                "start_service": {},
            }.items():
                mocked[name] = stack.enter_context(patch.object(launcher, name, **kwargs))
            yield mocked

    def records(self):
        return {name: dict(name=name, pid=i+100, birth="birth", port=port)
                for i, (name, port) in enumerate((("java",8080),("python",8765),("frontend",3000)))}

    def test_replacement_stops_and_starts_only_selected_service(self):
        for name in ("java", "python", "frontend"):
            with self.subTest(service=name), self.replacement_mocks(self.records()) as mocks:
                launcher.replace_service(self.opts(service=name))
                self.assertEqual([c.args[0]["name"] for c in mocks["stop_owned"].call_args_list], [name])
                self.assertEqual([c.args[0] for c in mocks["start_service"].call_args_list], [name])
                self.assertEqual(set(launcher.read_state()), {"java", "python", "frontend"} - {name})

    def test_replacement_preparation_failure_preserves_all_services(self):
        records = self.records()
        with self.replacement_mocks(records) as mocks:
            mocks["java_command"].side_effect = launcher.LaunchError("build failed")
            with self.assertRaises(launcher.LaunchError):
                launcher.replace_service(self.opts(service="java"))
            mocks["stop_owned"].assert_not_called()
            mocks["start_service"].assert_not_called()
        self.assertEqual(launcher.read_state(), records)

    def test_replacement_missing_dependency_leaves_old_python_running(self):
        with self.replacement_mocks(self.records()) as mocks:
            mocks["require_service"].side_effect = launcher.LaunchError("offline")
            with self.assertRaises(launcher.LaunchError):
                launcher.replace_service(self.opts(service="python"))
            mocks["stop_owned"].assert_not_called()

    def test_java_replacement_never_starts_missing_mysql(self):
        with self.replacement_mocks(self.records()) as mocks:
            mocks["port_open"].side_effect = lambda host, port: port != 3306
            with self.assertRaises(launcher.LaunchError):
                launcher.replace_service(self.opts(service="java"))
            mocks["ensure_mysql"].assert_not_called()
            mocks["java_command"].assert_not_called()
            mocks["stop_owned"].assert_not_called()

    def test_replacement_refuses_external_target_without_killing(self):
        with self.replacement_mocks({}) as mocks:
            with self.assertRaises(launcher.LaunchError):
                launcher.replace_service(self.opts(service="python"))
            mocks["stop_owned"].assert_not_called()
            mocks["start_service"].assert_not_called()

    def test_replacement_cannot_change_port_while_dependent_is_running(self):
        with self.replacement_mocks(self.records()) as mocks:
            # The new port is free, but the live Python still points to the old Java port.
            mocks["port_open"].side_effect = lambda host, port: port != 8081
            with self.assertRaises(launcher.LaunchError):
                launcher.replace_service(self.opts(service="java", backend_port=8081))
            mocks["stop_owned"].assert_not_called()

    def test_static_frontend_update_does_not_restart_python_or_java(self):
        with self.replacement_mocks(self.records()) as mocks:
            launcher.replace_service(self.opts(service="frontend", ui_static=True))
            mocks["prepare_frontend"].assert_called_once_with(False)
            mocks["start_service"].assert_not_called()
            self.assertEqual([c.args[0]["name"] for c in mocks["stop_owned"].call_args_list], ["frontend"])
            self.assertEqual(set(launcher.read_state()), {"java", "python"})

    def test_python_replacement_preserves_notification_switch(self):
        records = self.records()
        records["python"]["command"] = ["python", "--no-wechat"]
        with self.replacement_mocks(records) as mocks:
            launcher.replace_service(self.opts(service="python", no_wechat=None))
            self.assertIn("--no-wechat", mocks["start_service"].call_args.args[2])

    def test_failed_replacement_cleans_only_new_target(self):
        def fail(name, port, command, cwd, env, probe, state, created, timeout):
            record = dict(name=name, pid=444, birth="new", port=port)
            state[name] = record
            created.append(record)
            raise launcher.LaunchError("timeout")
        with self.replacement_mocks(self.records()) as mocks:
            mocks["start_service"].side_effect = fail
            with self.assertRaises(launcher.LaunchError):
                launcher.replace_service(self.opts(service="python"))
            self.assertEqual([c.args[0]["name"] for c in mocks["stop_owned"].call_args_list], ["python", "python"])
            self.assertEqual(set(launcher.read_state()), {"java", "frontend"})

    def test_stop_single_service_preserves_other_manifest_entries(self):
        launcher.write_state(self.records())
        with patch.object(launcher, "stop_owned") as stop:
            launcher.stop("python")
        self.assertEqual([c.args[0]["name"] for c in stop.call_args_list], ["python"])
        self.assertEqual(set(launcher.read_state()), {"java", "frontend"})

    def test_single_service_restart_cli_never_calls_global_stop(self):
        with patch.object(launcher.sys, "argv", ["start_project.py", "--service", "python", "--restart"]), \
             patch.object(launcher, "replace_service", return_value=0) as replace, \
             patch.object(launcher, "stop") as stop:
            self.assertEqual(launcher.main(), 0)
        stop.assert_not_called()
        self.assertEqual(replace.call_args.args[0].service, "python")

    def test_single_service_starts_when_target_is_absent(self):
        records = self.records()
        del records["python"]
        with self.replacement_mocks(records) as mocks:
            mocks["port_open"].return_value = False
            launcher.replace_service(self.opts(service="python"))
            mocks["stop_owned"].assert_not_called()
            self.assertEqual(mocks["start_service"].call_args.args[0], "python")

    def test_default_static_frontend_has_no_process_to_replace(self):
        records = self.records()
        del records["frontend"]
        with self.replacement_mocks(records) as mocks:
            mocks["port_open"].return_value = False
            launcher.replace_service(self.opts(service="frontend"))
            mocks["prepare_frontend"].assert_called_once_with(False)
            mocks["stop_owned"].assert_not_called()
            mocks["start_service"].assert_not_called()
            self.assertEqual(launcher.read_state(), records)


if __name__=="__main__":
    unittest.main()
