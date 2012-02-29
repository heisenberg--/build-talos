function LagDuringLoad(fe) {
  //benchmark controller
  this._fe = fe;
}

LagDuringLoad.prototype = {
  _timeoutDelay: 100,
  
  scheduleNextEvent: function() {
    let self = this;
    function timeout() {
      // Deal with timeouts that fire sooner than expected
      let diff = (new Date() - self._beforeTimeout) - self._timeoutDelay;
      if (diff > 0)
        self._fe.report.loadlag.push(diff);
      self.scheduleNextEvent();
    }
    if (Browser.selectedTab.isLoading()) {
      this._beforeTimeout = new Date()
      this._timeout = setTimeout(timeout, this._timeoutDelay);
    } else {
      //done with loading
      setTimeout(function() {self._fe.nextTest()}, 5000);
    }
  },
  
  go: function () {
    let browser = Browser.selectedBrowser;
    let self = this;
    
    function dummy() {
    }
  

    let url = "http://www.iol.co.za";
    if (self._fe.talos == true) {
      url = "http://" + self._fe.webServer + "/startup_test/fennecmark/wikipedia.html";
    }
    browser.loadURI(url, null, null, false);
    self.scheduleNextEvent();
  }
}