from __future__ import print_function

import os
import subprocess
from unittest import skipIf
from tornado.options import define, options
from tornado.process import Subprocess
from tornado.testing import gen_test
from tornado.web import Application

from tornado_http2.test.util import AsyncHTTP2TestCase

define("h2spec_section", type=str, multiple=True,
       help="h2spec section to run (e.g. '6.2')")

# To create or update the GLOCKFILE, set GOPATH to a temporary
# directory and run:
# go get github.com/robfig/glock
# go get -u github.com/summerwind/h2spec/cmd/h2spec
# glock cmd -n foo github.com/summerwind/h2spec/cmd/h2spec
GLOCKFILE = b"""\
cmd github.com/summerwind/h2spec/cmd/h2spec
github.com/summerwind/h2spec c4e383421fb7fd265f5c5e3392341e301f86ff67
golang.org/x/net 0cb26f788dd4625d1956c6fd97ffc4c90669d129
"""

@skipIf("H2SPEC_GOPATH" not in os.environ,
        "H2SpecTest only run when H2SPEC_GOPATH is set")
class H2SpecTest(AsyncHTTP2TestCase):
    def setUp(self):
        super(H2SpecTest, self).setUp()
        env = dict(os.environ, GOPATH=os.environ["H2SPEC_GOPATH"])
        glock_path = os.path.join(env["GOPATH"], "bin", "glock")
        if not os.path.exists(glock_path):
            subprocess.check_call(["go", "get", "github.com/robfig/glock"],
                                  env=env)
        glock_proc = subprocess.Popen([glock_path, "sync", "-n", ""], env=env,
                                      stdin=subprocess.PIPE,
                                      stdout=subprocess.PIPE,
                                      stderr=subprocess.STDOUT)
        out, _ = glock_proc.communicate(GLOCKFILE)
        if glock_proc.returncode:
            print(out)
            raise RuntimeError("glock failed with exit code %d",
                               glock_proc.returncode)
        self.h2spec_path = os.path.join(env["GOPATH"], "bin", "h2spec")

    def get_app(self):
        return Application()

    # This encapsulates a lot of tests, and when things are failing
    # it can take a while to run, so give it a longer timeout.
    @gen_test(timeout=60)
    def test_h2spec(self):
        h2spec_cmd = [self.h2spec_path, "-p",
                      str(self.get_http_port())]
        for section in options.h2spec_section:
            h2spec_cmd.extend(["-s", section])
        h2spec_proc = Subprocess(h2spec_cmd)
        yield h2spec_proc.wait_for_exit()
