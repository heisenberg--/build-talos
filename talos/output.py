# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""output formats for Talos"""

import filter
import mozinfo
import post_file
import time
import urllib
import urlparse
import utils
from StringIO import StringIO

try:
    import json
except ImportError:
    import simplejson as json

def filesizeformat(bytes):
    """
    Format the value like a 'human-readable' file size (i.e. 13 KB, 4.1 MB, 102
    bytes, etc).
    """
    bytes = float(bytes)
    formats = ('B', 'KB', 'MB')
    for f in formats:
        if bytes < 1024:
            return "%.1f%s" % (bytes, f)
        bytes /= 1024
    return "%.1fGB" % bytes #has to be GB

class Output(object):
    """abstract base class for Talos output"""

    @classmethod
    def check(cls, urls):
        """check to ensure that the urls are valid"""

    def __init__(self, results):
        """
        - results : TalosResults instance
        """
        self.results = results

    def __call__(self):
        """return list of results strings"""
        raise NotImplementedError("Abstract base class")

    def output(self, results, results_url):
        """output to the results_url
        - results_url : http:// or file:// URL
        - results : list of results
        """

        # parse the results url
        results_url_split = urlparse.urlsplit(results_url)
        results_scheme, results_server, results_path, _, _ = results_url_split

        if results_scheme in ('http', 'https'):
            self.post(results, results_server, results_path, results_scheme)
        elif results_scheme == 'file':
            f = file(results_path, 'w')
            for result in results:
                f.write(str(result))
            f.close()
        else:
            raise NotImplementedError("%s: %s - only http://, https://, and file:// supported" % (self.__class__.__name__, results_url))

    def post(self, results, server, path, scheme):
        raise NotImplementedError("Abstract base class")

    @classmethod
    def shortName(cls, name):
        """short name for counters"""
        names = {"Working Set": "memset",
                 "% Processor Time": "%cpu",
                 "Private Bytes": "pbytes",
                 "RSS": "rss",
                 "XRes": "xres",
                 "Modified Page List Bytes": "modlistbytes",
                 "Main_RSS": "main_rss",
                 "Content_RSS": "content_rss"}
        return names.get(name, name)

    @classmethod
    def isMemoryMetric(cls, resultName):
        """returns if the result is a memory metric"""
        memory_metric = ['memset', 'rss', 'pbytes', 'xres', 'modlistbytes', 'main_rss', 'content_rss'] #measured in bytes
        return bool([i for i in memory_metric if i in resultName])

    @classmethod
    def responsiveness_Metric(cls, val_list):
        return round(sum([int(x)*int(x) / 1000000.0 for x in val_list]))


class GraphserverOutput(Output):

    retries = 5   # number of times to attempt to contact graphserver
    info_format = ['title', 'testname', 'branch_name', 'sourcestamp', 'buildid', 'date']
    amo_info_format = ['browser_name', 'browser_version', 'addon_id']

    @classmethod
    def check(cls, urls):
        # ensure results_url link exists
        post_file.test_links(*urls)

    def __call__(self):
        """
        results to send to graphserver:
        construct all the strings of data, one string per test and one string  per counter
        """

        result_strings = []

        info_dict = dict(title=self.results.title,
                         date=self.results.date,
                         branch_name=self.results.browser_config['branch_name'],
                         sourcestamp=self.results.browser_config['sourcestamp'],
                         buildid=self.results.browser_config['buildid'],
                         browser_name=self.results.browser_config['browser_name'],
                         browser_version=self.results.browser_config['browser_version'],
                         addon_id=self.results.browser_config['addon_id']
                         )

        for test in self.results.results:

            utils.debug("Working with test: %s" % test.name())


            # get full name of test
            testname = test.name()
            if test.format == 'tpformat':
                # for some reason, we append the test extension to tp results but not ts
                # http://hg.mozilla.org/build/talos/file/170c100911b6/talos/run_tests.py#l176
                testname += self.results.test_name_extension

            utils.stamped_msg("Generating results file: %s" % test.name(), "Started")

            vals = []
            for result in test.results:
                # per test filters
                _filters = self.results.filters
                if 'filters' in test.test_config:
                    try:
                        _filters = filter.filters_args(test.test_config['filters'])
                    except AssertionError, e:
                        raise utils.talosError(str(e))

                vals.extend(result.values(_filters))
            result_strings.append(self.construct_results(vals, testname=testname, **info_dict))
            utils.stamped_msg("Generating results file: %s" % test.name(), "Stopped")

            # counter results
            for cd in test.all_counter_results:
                for counter_type, values in cd.items():

                    # get the counter name
                    counterName = '%s_%s' % (test.name() , self.shortName(counter_type))
                    if not values:
                        # failed to collect any data for this counter
                        utils.stamped_msg("No results collected for: " + counterName, "Error")
                        continue

                    # counter values
                    vals = [[x, 'NULL'] for x in values]

                    # append test name extension but only for tpformat tests
                    if test.format == 'tpformat':
                        counterName += self.results.test_name_extension

                    info = info_dict.copy()
                    info['testname'] = counterName

                    # append the counter string
                    utils.stamped_msg("Generating results file: %s" % counterName, "Started")
                    result_strings.append(self.construct_results(vals, **info))
                    utils.stamped_msg("Generating results file: %s" % counterName, "Stopped")


        return result_strings

    def responsiveness_test(self, testname):
        """returns if the test is a responsiveness test"""
        # XXX currently this just looks for the string
        # 'responsiveness' in the test name.
        # It would be nice to be more declarative about this
        return 'responsiveness' in testname

    def construct_results(self, vals, testname, **info):
        """
        return results string appropriate to graphserver
        - vals: list of 2-tuples: [(val, page)
        - kwargs: info necessary for self.info_format interpolation
        see https://wiki.mozilla.org/Buildbot/Talos/DataFormat
        """

        info['testname'] = testname
        info_format = self.info_format
        responsiveness = self.responsiveness_test(testname)
        _type = 'VALUES'
        if responsiveness:
            _type = 'AVERAGE'
        elif self.results.amo:
            _type = 'AMO'
            info_format = self.amo_info_format

        # ensure that we have all of the info data available
        missing = [i for i in info_format if i not in info]
        if missing:
            raise utils.talosError("Missing keys: %s" % missing)
        info = ','.join([str(info[key]) for key in info_format])

        # write the data
        buffer = StringIO()
        buffer.write("START\n")
        buffer.write("%s\n" % _type)
        buffer.write('%s\n' % info)
        if responsiveness:
            # write some kind of average
            buffer.write("%s\n" % self.responsiveness_Metric([val for (val, page) in vals]))
        else:
            for i, (val, page) in enumerate(vals):
                buffer.write("%d,%.2f,%s\n" % (i,float(val), page))
        buffer.write("END")
        return buffer.getvalue()

    def process_Request(self, post):
        """get links from the graphserver response"""
        links = ""
        lines = post.split('\n')
        for line in lines:
            if line.find("RETURN\t") > -1:
                line = line.replace("RETURN\t", "")
                links +=  line+ '\n'
            utils.debug("process_Request line: %s" % line)
        if not links:
            raise utils.talosError("send failed, graph server says:\n%s" % post)
        return links

    def post(self, results, server, path, scheme):
        """post results to the graphserver"""

        links = ''
        wait_time = 5 # number of seconds between each attempt

        for index, data_string in enumerate(results):

            times = 0
            msg = ""
            while times < self.retries:
                utils.noisy("Posting result %d of %d to %s://%s%s, attempt %d" % (index, len(results), scheme, server, path, times))
                try:
                    links += self.process_Request(post_file.post_multipart(server, path, files=[("filename", "data_string", data_string)]))
                    break
                except utils.talosError, e:
                    msg = e.msg
                except Exception, e:
                    msg = str(e)
                times += 1
                time.sleep(wait_time)
                wait_time *= 2
            else:
                raise utils.talosError("Graph server unreachable (%d attempts)\n%s" % (self.retries, msg))

        if not links:
            # you're done
            return links
        lines = links.split('\n')

        # print graph results
        if self.results.amo:
            self.amo_results_from_graph(lines)
        else:
            self.results_from_graph(lines, server)

        # return links from graphserver
        return links

    def amo_results_from_graph(self, lines):
        """print results from AMO graphserver POST submission"""
        #only get a pass/fail back from the graph server
        for line in lines:
            if not line:
                continue
            if line.lower() in ('success',):
                print 'RETURN:addon results inserted successfully'

    def results_from_graph(self, lines, results_server):
        """print results from graphserver POST submission"""
        # TODO: document what response is actually supposed to look like

        url_format = "http://%s/%s"
        link_format= "<a href=\'%s\'>%s</a>"
        first_results = 'RETURN:<br>'
        last_results = ''
        full_results = '\nRETURN:<p style="font-size:smaller;">Details:<br>'

        for line in lines:
            if not line:
                continue
            linkvalue = -1
            linkdetail = ""
            values = line.split("\t")
            linkName = values[0]
            if len(values) == 2:
                linkdetail = values[1]
            else:
                linkvalue = float(values[1])
                linkdetail = values[2]
            if linkvalue > -1:
                if self.isMemoryMetric(linkName):
                    linkName += ": " + filesizeformat(linkvalue)
                else:
                    linkName += ": %s" % linkvalue
                url = url_format % (results_server, linkdetail)
                link = link_format % (url, linkName)
                first_results = first_results + "\nRETURN:" + link + "<br>"
            else:
                url = url_format % (results_server, linkdetail)
                link = link_format % (url, linkName)
                last_results = last_results + '| ' + link + ' '
        full_results = first_results + full_results + last_results + '|</p>'
        print full_results


class DatazillaOutput(Output):

    def __call__(self):
        retval = []
        for test in self.results.results:

            # serialize test results
            results = {}
            if test.format == 'tsformat':
                raw_vals = []
                for result in test.results:
                    raw_vals.extend(result.raw_values())
                results[test.name()] = raw_vals
            elif test.format == 'tpformat':
                for result in test.results:
                    # XXX this will not work for manifests which list
                    # the same page name twice. It also ignores cycles
                    for page, val in result.raw_values():
                        results.setdefault(page, []).extend(val)

            # test options
            testrun = {'date': self.results.date,
                       'suite': "Talos %s" % test.name(),
                       'options': self.run_options(test)}

            # platform
            machine = self.test_machine()

            # build information
            browser_config = self.results.browser_config
            test_build = {'name': browser_config['browser_name'],
                          'version': browser_config['browser_version'],
                          'revision': browser_config['sourcestamp'],
                          'branch': browser_config['branch_name'],
                          'id': browser_config['buildid']}

            # counters results_aux data
            results_aux = {}
            for cd in test.all_counter_results:
                for name, vals in cd.items():
                    results_aux[self.shortName(name)] = vals

            # munge this together
            result = {'test_machine': machine,
                      'test_build': test_build,
                      'testrun': testrun,
                      'results': results,
                      'results_aux': results_aux}

            # serialize to a JSON string
            retval.append(json.dumps(result))

        return retval

    def post(self, results, server, path, scheme):

        try:
            for result in results:
                post_file.post_multipart(results_server, results_path, fields=[("data", urllib.quote(result))])
            print "done posting raw results to staging server"
        except:
            # This is for posting to a staging server, we can ignore the error
            print "was not able to post raw results to staging server"

    def run_options(self, test):
        """test options for datazilla"""

        options = {}
        test_options = ['rss', 'tpchrome', 'tpmozafterpaint', 'tpcycles', 'tppagecycles', 'tprender', 'tpdelay', 'responsiveness', 'shutdown']
        for option in test_options:
            if option not in test.test_config:
                continue
            options[option] = test.test_config[option]
        if test.extensions is not None:
            options['extensions'] = [{'name': extension}
                                     for extension in test.extensions]
        return options

    def test_machine(self):
        """return test machine platform in a form appropriate to datazilla"""
        if self.results.remote:
            # TODO: figure out how to not hardcode this, specifically the version !!
            # should probably come from the agent (sut/adb) and passed in
            platform = "Android"
            version = "4.0.3"
            processor = "arm"
        else:
            platform = mozinfo.os
            version = mozinfo.version
            processor = mozinfo.processor

        return dict(name=self.results.title, os=platform, osversion=version, platform=processor)


# available output formats
formats = {'datazilla_urls': DatazillaOutput,
           'results_urls': GraphserverOutput}

try:
    from amo.amo_api import upload_amo_results, amo_results_data
    # depends on httplib2 and json/simplejson so we conditionally import it

    class AMOOutput(Output):
        def __call__(self):
            # TODO: do we only test ts, if not, can we ensure that we are not trying to uplaod ts_rss, etc...
            # see http://hg.mozilla.org/build/talos/file/170c100911b6/talos/run_tests.py#l227
            retval = []
            for test in self.results.results:
                if test.name() != 'ts':
                    continue
                vals = []
                for cycle in test.results:
                    vals.extend(cycle.raw_values())

                retval.append(amo_results_data(self.results.browser_config['addon_id'],
                                               self.results.browser_config['browser_version'],
                                               self.results.browser_config['process'],
                                               test.name(),
                                               vals
                                               )
                              )

        def post(self, results, server, path, scheme):
            for result in results:
                upload_amo_results(result, server, path, scheme)

    formats['amo'] = AMOOutput

except ImportError:
    pass