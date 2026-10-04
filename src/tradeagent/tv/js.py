"""JavaScript evaluated inside TradingView Desktop chart tabs.

Uses TradingView's undocumented internal API (verified on Desktop 3.4.1, 2026-10-02; see
docs/TRADINGVIEW-SETUP.md). Every snippet returns plain JSON. Times inside TradingView are UNIX seconds.
"""

from __future__ import annotations

import json
from typing import Any

_HELPERS = """
  var api = window.TradingViewApi;
  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
  function userStudies(i) {
    return api.chart(i).getAllStudies().filter(function (s) { return String(s.id).indexOf('ESD$') !== 0; });
  }
  function seriesState(cw) {
    var ms = cw.model().mainSeries();
    var bars = ms.bars();
    return {
      symbol: ms.symbol(), interval: ms.interval(), bars: bars.size(),
      last_bar_time: bars.size() ? bars.valueAt(bars.lastIndex())[0] : null,
      series_status: ms._status.value().seriesStatus, is_loading: ms.isLoading()
    };
  }
  function rowAt(series, t) {
    var last = series.lastIndex(), first = series.firstIndex();
    if (last === null || first === null) return null;
    for (var i = last; i >= Math.max(first, last - 2000); i--) {
      var v = series.valueAt(i);
      if (v && v[0] === t) return v;
      if (v && v[0] < t) return null;
    }
    return null;
  }
"""

_TAB_STATE = """function () {
""" + _HELPERS + """
  return {
    layout_id: api.layoutId(), layout_name: api.layoutName(),
    charts: api._chartWidgetCollection.getAll().map(function (cw, i) {
      var st = seriesState(cw);
      st.index = i;
      st.studies = userStudies(i).map(function (s) { return s.name; });
      return st;
    })
  };
}"""

# Optionally switch the symbol, then wait until every chart in the tab is loaded, has at least
# minBars of history, and every study has recomputed over that history.
_PREPARE = """async function (targetSymbol, minBars, timeoutMs, maxRequests, acceptLess) {
""" + _HELPERS + """
  var charts = api._chartWidgetCollection.getAll();
  var started = Date.now();
  var switched = false;
  if (targetSymbol && charts[0].model().mainSeries().symbol() !== targetSymbol) {
    api.chart(0).setSymbol(targetSymbol, {});
    switched = true;
  }
  var sawLoading = !switched;
  function seriesReady(cw) {
    var ms = cw.model().mainSeries();
    return (!targetSymbol || ms.symbol() === targetSymbol) && ms._status.value().seriesStatus === 3 && !ms.isLoading();
  }
  function studiesReady(cw, i) {
    var model = cw.model().model();
    var bars = cw.model().mainSeries().bars();
    if (!bars.size()) return false;
    var lastTime = bars.valueAt(bars.lastIndex())[0];
    return userStudies(i).every(function (st) {
      var src = model.dataSourceForId(st.id);
      if (!src || src.isLoading() || src.isFailed()) return false;
      var data = src.data();
      return data.size() === bars.size() && data.valueAt(data.lastIndex())[0] === lastTime;
    });
  }
  var requests = charts.map(function () { return 0; });
  var ok = false;
  while (Date.now() - started < timeoutMs) {
    await sleep(200);
    ok = true;
    for (var i = 0; i < charts.length; i++) {
      var cw = charts[i];
      var ms = cw.model().mainSeries();
      if (ms._status.value().seriesStatus !== 3 || ms.isLoading()) sawLoading = true;
      if (!seriesReady(cw)) { ok = false; continue; }
      if (ms.bars().size() < minBars) {
        var more = ms.requestMoreDataAvailable() && requests[i] < maxRequests;
        if (more) {
          ms.requestMoreData(minBars - ms.bars().size() + 10);
          requests[i]++;
        }
        // A backfill takes whatever history exists once TradingView has no more to give.
        if (more || !acceptLess) { ok = false; continue; }
      }
      if (!studiesReady(cw, i)) ok = false;
    }
    // After a symbol switch the old data still looks "ready" for a moment; wait for the reload.
    if (ok && (sawLoading || Date.now() - started > 3000)) break;
    ok = false;
  }
  return {
    ok: ok, ms: Date.now() - started,
    charts: charts.map(function (cw, i) {
      var st = seriesState(cw);
      st.index = i;
      st.studies_ready = studiesReady(cw, i);
      st.history_requests = requests[i];
      return st;
    })
  };
}"""

# Values of the catalog plots on the candle that opened at barTime, plus the candle itself.
_READ_CLOSED = """function (spec, chartIndex, barTime) {
""" + _HELPERS + """
  var charts = api._chartWidgetCollection.getAll();
  if (chartIndex >= charts.length) return { error: 'no chart at index ' + chartIndex };
  var cw = charts[chartIndex];
  var model = cw.model().model();
  var out = seriesState(cw);
  out.bar_time = barTime;
  out.values = {};
  out.problems = [];
  var bar = rowAt(cw.model().mainSeries().bars(), barTime);
  if (!bar) { out.problems.push('candle ' + barTime + ' not loaded'); return out; }
  out.ohlcv = bar.slice(1, 6);
  var studies = userStudies(chartIndex);
  Object.keys(spec).forEach(function (key) {
    var ind = spec[key];
    var st = studies.filter(function (s) { return s.name === ind.study; })[0];
    if (!st) { out.problems.push(key + ': study "' + ind.study + '" is not on the chart'); return; }
    var src = model.dataSourceForId(st.id);
    var meta = src.metaInfo();
    var plots = meta.plots || [];
    var row = rowAt(src.data(), barTime);
    if (!row) { out.problems.push(key + ': no values for the candle'); return; }
    var vals = {};
    ind.fields.forEach(function (f) {
      var pos = -1;
      for (var p = 0; p < plots.length; p++) { if (plots[p].id === f.plot) { pos = p + 1; break; } }
      var style = meta.styles ? meta.styles[f.plot] : null;
      var title = style ? style.title : null;
      if (pos < 0) { out.problems.push(key + '.' + f.name + ': ' + f.plot + ' does not exist'); return; }
      if (title !== f.title) { out.problems.push(key + '.' + f.name + ': title "' + title + '" expected "' + f.title + '"'); return; }
      var v = row[pos];
      if (f.kind === 'flag') vals[f.name] = (v === true || (typeof v === 'number' && isFinite(v) && v !== 0)) ? 1 : 0;
      else vals[f.name] = (typeof v === 'number' && isFinite(v)) ? v : null;
    });
    out.values[key] = vals;
  });
  return out;
}"""

# Non-colour inputs of the given studies on every chart of the tab (for the signal version).
_READ_INPUTS = """function (studyNames) {
""" + _HELPERS + """
  return api._chartWidgetCollection.getAll().map(function (cw, i) {
    var model = cw.model().model();
    var res = { interval: cw.model().mainSeries().interval(), studies: {} };
    userStudies(i).forEach(function (st) {
      if (studyNames.indexOf(st.name) < 0) return;
      var src = model.dataSourceForId(st.id);
      var types = {};
      (src.metaInfo().inputs || []).forEach(function (inp) { types[inp.id] = inp.type; });
      var childs = src.properties().childs().inputs.childs();
      var vals = {};
      Object.keys(childs).sort().forEach(function (k) {
        if (!/^in_\\d+$/.test(k) || types[k] === 'color') return;
        try { vals[k] = childs[k].value(); } catch (e) {}
      });
      res.studies[st.name] = vals;
    });
    return res;
  });
}"""

# Values of the catalog plots for every closed candle from fromTime on, skipping the first `warmup`
# loaded candles (indicators are still warming up there). Used to backfill history.
_READ_HISTORY = """function (spec, chartIndex, fromTime, warmup, maxRows) {
""" + _HELPERS + """
  function findIndex(series, t) {
    var lo = series.firstIndex(), hi = series.lastIndex();
    if (lo === null || hi === null) return -1;
    while (lo <= hi) {
      var mid = (lo + hi) >> 1, v = series.valueAt(mid);
      if (!v) return -1;
      if (v[0] === t) return mid;
      if (v[0] < t) lo = mid + 1; else hi = mid - 1;
    }
    return -1;
  }
  var charts = api._chartWidgetCollection.getAll();
  if (chartIndex >= charts.length) return { error: 'no chart at index ' + chartIndex };
  var cw = charts[chartIndex];
  var model = cw.model().model();
  var bars = cw.model().mainSeries().bars();
  var out = seriesState(cw);
  out.problems = [];
  out.rows = [];
  out.next_time = null;
  var studies = userStudies(chartIndex);
  var cols = [];
  Object.keys(spec).forEach(function (key) {
    var ind = spec[key];
    var st = studies.filter(function (s) { return s.name === ind.study; })[0];
    if (!st) { out.problems.push(key + ': study "' + ind.study + '" is not on the chart'); return; }
    var src = model.dataSourceForId(st.id);
    var meta = src.metaInfo();
    var plots = meta.plots || [];
    var fields = [];
    ind.fields.forEach(function (f) {
      var pos = -1;
      for (var p = 0; p < plots.length; p++) { if (plots[p].id === f.plot) { pos = p + 1; break; } }
      var style = meta.styles ? meta.styles[f.plot] : null;
      var title = style ? style.title : null;
      if (pos < 0 || title !== f.title) { out.problems.push(key + '.' + f.name + ': plot or title changed'); return; }
      fields.push({ name: f.name, pos: pos, kind: f.kind });
    });
    cols.push({ key: key, data: src.data(), fields: fields });
  });
  if (out.problems.length) return out;
  var first = bars.firstIndex() + warmup, last = bars.lastIndex() - 1;  // never the forming candle
  for (var i = first; i <= last; i++) {
    var b = bars.valueAt(i);
    if (!b || b[0] < fromTime) continue;
    var values = {}, complete = true;
    for (var c = 0; c < cols.length; c++) {
      var row = cols[c].data.valueAt(i);
      if (!row || row[0] !== b[0]) {
        var j = findIndex(cols[c].data, b[0]);
        row = j >= 0 ? cols[c].data.valueAt(j) : null;
      }
      if (!row) { complete = false; break; }
      var vals = {};
      cols[c].fields.forEach(function (f) {
        var v = row[f.pos];
        if (f.kind === 'flag') vals[f.name] = (v === true || (typeof v === 'number' && isFinite(v) && v !== 0)) ? 1 : 0;
        else vals[f.name] = (typeof v === 'number' && isFinite(v)) ? v : null;
      });
      values[cols[c].key] = vals;
    }
    if (complete) out.rows.push([b[0], b[1], b[2], b[3], b[4], b[5], values]);
    if (maxRows && out.rows.length >= maxRows) {
      if (i < last) out.next_time = bars.valueAt(i + 1)[0];
      break;
    }
  }
  return out;
}"""

_OPEN_LAYOUT_TAB = """async function (layoutId) {
  await window.TradingViewApi.loadLayoutFromServerByLayoutId(layoutId, true);
  return true;
}"""

_RELOAD = """function () { setTimeout(function () { location.reload(); }, 100); return true; }"""

# Time axis of every chart in the tab. 'system' = the computer's zone as TradingView itself sees it. A zone that
# TradingView does not list falls back to a listed zone with the same UTC offset now, else UTC. Display only:
# intraday candles follow the exchange session, so bars, indicator values and bar times stay the same.
_SET_TIMEZONE = """function (wanted) {
  var api = window.TradingViewApi;
  var count = api._chartWidgetCollection.getAll().length;
  var system = Intl.DateTimeFormat().resolvedOptions().timeZone;
  var target = wanted === 'system' ? system : wanted;
  var out = { wanted: wanted, target: target, changed: 0, charts: count };
  for (var i = 0; i < count; i++) {
    var tz = api.chart(i).getTimezoneApi();
    if (i === 0) {
      var listed = tz.availableTimezones();
      if (!listed.some(function (z) { return z.id === target; })) {
        var offset = wanted === 'system' ? -new Date().getTimezoneOffset() * 60000 : null;
        var same = listed.filter(function (z) { return offset !== null && (z.offset || 0) === offset && z.id !== 'exchange'; })[0];
        out.target = same ? same.id : 'Etc/UTC';
      }
    }
    if (tz.getTimezone().id !== out.target) { tz.setTimezone(out.target); out.changed++; }
  }
  return out;
}"""


def _call(fn: str, *args: Any) -> str:
    return "(" + fn + ")(" + ", ".join(json.dumps(a) for a in args) + ")"


def tab_state() -> str:
    return _call(_TAB_STATE)


def prepare(symbol: str | None, min_bars: int, timeout_ms: int, max_requests: int = 5, accept_less: bool = False) -> str:
    return _call(_PREPARE, symbol, min_bars, timeout_ms, max_requests, accept_less)


def read_closed(spec: dict[str, Any], chart_index: int, bar_time_s: int) -> str:
    return _call(_READ_CLOSED, spec, chart_index, bar_time_s)


def read_history(spec: dict[str, Any], chart_index: int, from_time_s: int, warmup: int, max_rows: int = 0) -> str:
    """Rows from from_time_s on; with max_rows, at most that many plus `next_time` to continue from."""
    return _call(_READ_HISTORY, spec, chart_index, from_time_s, warmup, max_rows)


def read_inputs(study_names: list[str]) -> str:
    return _call(_READ_INPUTS, study_names)


def open_layout_tab(layout_id: str) -> str:
    return _call(_OPEN_LAYOUT_TAB, layout_id)


def reload_tab() -> str:
    return _call(_RELOAD)


def set_timezone(wanted: str) -> str:
    return _call(_SET_TIMEZONE, wanted)
