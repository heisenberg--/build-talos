#!/usr/bin/env python

import os
import sys
import PerfConfigurator as pc
import utils
from PerfConfigurator import Configuration

class remotePerfConfigurator(pc.PerfConfigurator):

    replacements = pc.PerfConfigurator.replacements + ['deviceip', 'deviceroot', 'deviceport', 'fennecIDs']

    def __init__(self, **options):
        self.__dict__.update(options)
        self._remote = False
        if (self.deviceip <> '' or self.deviceport == -1):
            self._setupRemote()
            options['deviceroot'] = self.deviceroot

        #this depends on buildID which requires querying the device
        pc.PerfConfigurator.__init__(self, **options)

    def _setupRemote(self):
        try:
            self.testAgent = utils.testAgent(self.deviceip, self.deviceport)
            self.deviceroot = self.testAgent.getDeviceRoot()
        except:
            raise Configuration("Unable to connect to remote device '%s'" % self.deviceip)

        if self.deviceroot is None:
            raise Configuration("Unable to connect to remote device '%s'" % self.deviceip)

        self._remote = True

    def convertLine(self, line):
        # For NativeUI Fennec, we are working around bug 708793 and uploading a
        # unique machine name (defined via title) with a .n.  Currently a machine name
        # is a 1:1 mapping with the OS+hardware
        if self.nativeUI and not self.title.endswith(".n"):
          self.title = "%s.n" % self.title
        newline = pc.PerfConfigurator.convertLine(self, line)

        if 'remote:' in line:
            newline = 'remote: %s\n' % self._remote
        if 'talos.logfile:' in line:
            parts = line.split(':')
            if parts[1] != None and parts[1].strip() == '':
                lfile = os.path.join(os.getcwd(), 'browser_output.txt')
            elif self.browser_log != 'browser_output.txt':
                lfile = self.browser_log
            else:
                lfile = parts[1].strip().strip("'")
            lfile = self.deviceroot + '/' + lfile.split('/')[-1]
            newline = '%s: %s\n' % (parts[0], lfile)

        return newline

    def buildRemoteTwinopen(self):
        """
          twinopen needs to run locally as it is a .xul file.
          copy bits to <deviceroot>/talos and fix line to reference that
        """
        if self._remote == False:
            return

        files = ['page_load_test/quit.js',
                 'scripts/MozillaFileLogger.js',
                 'startup_test/twinopen/winopen.xul',
                 'startup_test/twinopen/winopen.js',
                 'startup_test/twinopen/child-window.html']

        talosRoot = self.deviceroot + '/talos/'
        for file in files:
            if self.testAgent.pushFile(file, talosRoot + file) == False:
                raise Configuration("Unable to copy twinopen file "
                                    + file + " to " + talosRoot + file)

    def convertUrlToRemote(self, url):
        """
        For a give url, add a webserver.
        In addition if there is a .manifest file specified, covert
        and copy that file to the remote device.
        """
        if self._remote == False:
            return url

        url = pc.PerfConfigurator.convertUrlToRemote(self, url)
        if 'winopen.xul' in url:
            self.buildRemoteTwinopen()
            url = 'file://' + self.deviceroot + '/talos/' + url

        # Take care of tpan/tzoom tests
        url = url.replace('webServer=', 'webServer=' + self.webserver);

        # Take care of the robocop based tests
        url = url.replace('class org.mozilla.fennec.tests', 'class %s.tests' % self.browser_path)
        return url

    def buildRemoteManifest(self, manifestName):
        """
           Push the manifest name to the remote device.
        """
        remoteName = self.deviceroot
        newManifestName = pc.PerfConfigurator.buildRemoteManifest(self, manifestName)

        remoteName += '/' + os.path.basename(manifestName)
        if self.testAgent.pushFile(newManifestName, remoteName) == False:
            raise Configuration("Unable to copy remote manifest file "
                                + newManifestName + " to " + remoteName)
        return remoteName

class remoteTalosOptions(pc.TalosOptions):

    def __init__(self, **kwargs):
        pc.TalosOptions.__init__(self, **kwargs)
        defaults = {}

        self.add_option("-r", "--remoteDevice", action="store",
                    type = "string", dest = "deviceip",
                    help = "Device IP (when using SUTAgent)")
        defaults["deviceip"] = ''

        self.add_option("-p", "--remotePort", action="store",
                    type="int", dest = "deviceport",
                    help = "SUTAgent port (defaults to 20701, specify -1 to use ADB)")
        defaults["deviceport"] = 20701

        self.add_option("--deviceRoot", action="store",
                    type = "string", dest = "deviceroot",
                    help = "path on the device that will hold files and the profile")
        defaults["deviceroot"] = ''

        self.add_option("--nativeUI", action = "store_true", dest = "nativeUI",
                    help = "Run tests on Fennec with a Native Java UI instead of the XUL UI")
        defaults["nativeUI"] = False

        self.add_option("--fennecIDs", action = "store", dest = "fennecIDs",
                    help = "Location of the fennec_ids.txt map file, used for robocop based tests")
        defaults["fennecIDs"] = ''

        defaults["sampleConfig"] = os.path.join(pc.here, 'remote.config')
        defaults["extensions"] = ['${talos}/pageloader']
        self.set_defaults(**defaults)

    def verifyCommandLine(self, args, options):
        options = pc.TalosOptions.verifyCommandLine(self, args, options)

        if options.develop:
            if options.webserver.startswith('localhost'):
                options.webserver = pc.getLanIp()

        #webServer can be used without remoteDevice, but is required when using remoteDevice
        if (options.deviceip != '' or options.deviceroot != ''):
            if (options.webserver == 'localhost'  or options.deviceip == ''):
                raise Configuration("When running Talos on a remote device, you need to provide a webServer and optionally a remotePort")

        if options.fennecIDs and not os.path.exists(options.fennecIDs):
            raise Configuration("Unable to find fennec_ids.txt, please ensure this file exists: %s" % options.fennecIDs)

        return options

def main(argv=sys.argv[1:]):
    parser = remoteTalosOptions()
    progname = parser.get_prog_name()

    try:
        options, args = parser.parse_args(argv)
        configurator = remotePerfConfigurator(**options.__dict__)
        configurator.writeConfigFile()
    except Configuration, err:
        print >> sys.stderr, "%s: %s" % (progname, str(err.msg))
        return 4
    except EnvironmentError, err:
        print >> sys.stderr, "%s: %s" % (progname, err)
        return 4
    # Note there is no "default" exception handler: we *want* a big ugly
    # traceback and not a generic error if something happens that we didn't
    # anticipate

    return 0

if __name__ == "__main__":
    sys.exit(main())
