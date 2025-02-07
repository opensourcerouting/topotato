/* eslint no-unused-vars: ["error", { "args": "none" }] */

function container_class(obj, classname) {
	while (obj.parentElement && !obj.classList.contains(classname))
		obj = obj.parentElement;
	return obj;
}

function container_tag(obj, tagname) {
	while (obj.parentElement && obj.tagName.toLowerCase() != tagname)
		obj = obj.parentElement;
	return obj;
}

/* exported raw_expand */
function raw_expand(obj, ev) {
	obj = container_class(obj, "e_cont");

	for (let target of obj.getElementsByClassName("e_hide")) {
		var et = container_class(target.parentElement, "e_cont");
		if (et != obj) {
			console.log("skip expanding", target);
			continue;
		}

		if (target.classList.contains("e_show")) {
			target.classList.remove("e_show");
		} else {
			target.classList.add("e_show");
		}
	}
	if (obj.classList.contains("e_expanded")) {
		obj.classList.remove("e_expanded");
	} else {
		obj.classList.add("e_expanded");
	}
	ev.stopPropagation();
}

/* hover infrastructure */

/* before new hover is shown: */
var hover_timer_in = null;
var hover_parent_pending = null;

/* current hover that is shown: */
var hover_parent = null;
var hover_child = null;

/* after leaving current hover: */
var hover_timer_out = null;

/* for debugging, set in console to make hover elements not get cleared */
var hover_stick = false;


function hover_clear() {
	if (hover_timer_out) {
		clearTimeout(hover_timer_out);
		hover_timer_out = null;
	}

	if (hover_child) {
		hover_child.parentElement.removeChild(hover_child);
		hover_child = null;
	}

	if (hover_parent) {
		hover_parent.classList.remove("hover-open");
		hover_parent = null;
	}

	hover_timer_out = null;
}

function hover_inner() {
	event.stopPropagation();

	if (hover_timer_out) {
		clearTimeout(hover_timer_out);
		hover_timer_out = null;
	}
	if (hover_timer_in) {
		clearTimeout(hover_timer_in);
		hover_parent_pending = null;
		hover_timer_in = null;
	}
}

function hover_in() {
	hover_timer_in = null;

	if (hover_parent) {
		hover_clear();
	} else if (hover_timer_out) {
		clearTimeout(hover_timer_out);
		hover_timer_out = null;
	}

	hover_parent = hover_parent_pending;
	hover_parent.classList.add("hover-open");
	hover_parent_pending = null;

	hover_parent.style.position = "relative";

	hover_child = document.createElement("div");
	hover_child.classList.add("hover");
	hover_child.style.marginTop = `${hover_parent.offsetHeight}px`;
	hover_child.style.marginLeft = "20px";
	hover_parent.insertBefore(hover_child, hover_parent.childNodes[0]);

	hover_child.onmouseover = hover_inner;

	hover_parent.hover_handler(hover_parent);
}

function hover_mouseout() {
	event.stopPropagation();
	if (hover_timer_in) {
		clearTimeout(hover_timer_in);
		hover_timer_in = null;
		hover_parent_pending = null;
	}
	if (!hover_stick && !hover_timer_out) {
		hover_timer_out = setTimeout(hover_clear, 800);
	}
}

function hover_mouseover() {
	event.stopPropagation();

	let hover_e = event.target;
	while (hover_e.onmouseover !== hover_mouseover) {
		hover_e = hover_e.parentElement;
	}

	if (hover_timer_in) {
		clearTimeout(hover_timer_in);
		hover_timer_in = null;
		hover_parent_pending = null;
	}
	if (hover_e === hover_parent) {
		if (hover_timer_out) {
			clearTimeout(hover_timer_out);
		}
		hover_timer_out = null;
		return;
	}
	hover_parent_pending = hover_e;
	if (hover_child) {
		hover_timer_in = setTimeout(hover_in, 400);
	} else {
		hover_timer_in = setTimeout(hover_in, 100);
	}
}

/* anchor processing */

var anchor_active = null;
var anchor_current = {};
const anchor_defaults = {
	"log": "ewni",
	"cli": null,
};

const log_keys = {
	"prio-error": "e",
	"prio-warn": "w",
	"prio-notif": "n",
	"prio-info": "i",
	"prio-debug": "d",
	"prio-startup": "s",
};

const log_rules_setup =  [
	{ prefix: "h:", field: "rname", ref: obj => obj.data.router },
	{ prefix: "u:", field: "uid", ref: obj => obj.data.uid },
	{ prefix: "d:", field: "daemon", ref: obj => obj.data.daemon },
	{ prefix: "p:", field: "prio", ref: obj => obj.data.prio }
];
var log_rules;

function log_empty_rule() {
	let ret = new Object();
	for (const setup of log_rules_setup)
		ret[setup.field] = new Array();
	return ret;
}

function log_show(key, sel) {
	let enabled = {};
	let cbox = document.getElementById("cf-log");

	let items = sel.split("/");
	sel = items.shift();
	if (sel == "-") {
		cbox.checked = false;
		for (const classname of Object.keys(log_keys)) {
			cbox = document.getElementById("cf-".concat(classname));
			cbox.disabled = true;
		}
	} else {
		cbox.checked = true;
		for (const [classname, ctlchar] of Object.entries(log_keys)) {
			enabled[classname] = (sel.indexOf(ctlchar) >= 0);

			cbox = document.getElementById("cf-".concat(classname));
			cbox.checked = enabled[classname];
			cbox.disabled = false;
		}
	}

	log_rules = new Array();
	for (const rule of items) {
		let lr = log_empty_rule();

		if (rule.startsWith("+")) {
			lr.sense = true;
		} else if (rule.startsWith("-")) {
			lr.sense = false;
		} else {
			continue;
		}

		for (const detail of rule.substr(1).split(".")) {
			for (const setup of log_rules_setup) {
				if (!detail.startsWith(setup.prefix))
					continue;
				lr[setup.field].push(detail.substr(setup.prefix.length));
				break;
			}
		}

		log_rules.push(lr);
	}

	for (let target of Array.from(document.getElementsByClassName("logmsg"))) {
		var enable = false;
		var prio = Array.from(target.classList).filter(s => s.startsWith("prio-"))[0];

		if (prio === undefined)
			prio = "prio-startup";
		if (prio in enabled)
			enable = enabled[prio];
		else
			enable = (sel != "-");
		for (const rule of log_rules) {
			let match = true;
			for (const setup of log_rules_setup) {
				if (rule[setup.field].length == 0)
					continue;
				if (!rule[setup.field].includes(setup.ref(target.obj))) {
					match = false;
					break;
				}
			}
			if (match)
				enable = rule.sense;
		}
		if (target.classList.contains("assert-match"))
			enable = true;
		target.style.display = enable ? "contents" : "none";
	}
}

function cli_show(key, sel) {
	var show_normal = (sel !== "-");
	var show_repeat = (sel === "r");

	console.log("cli_show", key, sel);
	for (let target of Array.from(document.getElementsByClassName("clicmd"))) {
		var vis = target.classList.contains("cli-same") ? show_repeat : show_normal;

		if (vis)
			target.style.display = "contents";
		else
			target.style.display = "none";
	}

	document.getElementById("cf-cli-repeat").disabled = !show_normal;
}

const anchor_funcs = {
	"log": log_show,
	"cli": cli_show,
};

function anchor_apply(opts) {
	for (const [key, val] of Object.entries(opts)) {
		console.log("apply", key, val, anchor_current[key]);
		if ((key in anchor_current) && (anchor_current[key] === val))
			continue;

		anchor_funcs[key](key, val);
		anchor_current[key] = val;
	}
}

var prev_anchor;

function anchor_update() {
	var loc = decodeURIComponent(location.hash);

	if (loc.startsWith("#")) {
		loc = loc.substr(1);
	}

	let args = loc.split(",");
	let anchor = args.shift();

	prev_anchor = anchor_active;
	if (anchor_active !== null) {
		anchor_active.classList.remove("active");
	}
	anchor_active = null;

	if (anchor) {
		let anchored = document.getElementById(anchor);
		if (anchored) {
			anchor_active = anchored;
			if (anchored !== prev_anchor)
				anchored.scrollIntoView();
			anchor_active.classList.add("active");
		}
	}

	let opts = {...anchor_defaults};
	for (let arg of args) {
		if (arg === "")
			continue;

		let s = arg.split("=");
		let key = s.shift();
		let val = s.join("=");

		if (key in anchor_funcs) {
			opts[key] = val;
		} else {
			console.log("unknown parameter", arg);
		}
	}

	console.log("apply options:", opts);
	anchor_apply(opts);
}

function anchor_export(opts) {
	var out = [];

	if (anchor_active !== null)
		out.push(anchor_active.id);
	else
		out.push("");

	for (const [key, val] of Object.entries(opts)) {
		if ((key in anchor_defaults) && (anchor_defaults[key] === val))
			continue;

		out.push(key + "=" + val);
	}
	out.push("");

	location.hash = "#".concat(out.join(","));
}

/* exported onclicklog */
function onclicklog(evt) {
	const srcid = evt.target.id;
	const checked = evt.target.checked;

	let opts = {...anchor_current};

	let cur_log = opts["log"].split("/");
	let log_basic;

	cur_log.shift();

	if (srcid == "cf-log" && !checked)
		log_basic = "-";
	else {
		var optstr = [];

		for (const [classname, ctlchar] of Object.entries(log_keys)) {
			if (document.getElementById("cf-".concat(classname)).checked)
				optstr.push(ctlchar);
		}
		log_basic = optstr.join("");
	}
	cur_log.unshift(log_basic);
	opts["log"] = cur_log.join("/");

	anchor_export(opts);
}

/* exported onclickcli */
function onclickcli(evt) {
	let opts = {...anchor_current};

	if (!document.getElementById("cf-cli").checked)
		opts["cli"] = "-";
	else if (document.getElementById("cf-cli-repeat").checked)
		opts["cli"] = "r";
	else
		opts["cli"] = null;

	anchor_export(opts);
}

function onclickclicmd(evt) {
	evt.stopPropagation();

	let pobj = container_class(evt.target, "clicmd");
	let obj = pobj.nextElementSibling;
	if (obj.style.display == "contents") {
		pobj.classList.remove("cli-expanded");
		obj.style.display = "none";
	} else {
		pobj.classList.add("cli-expanded");
		obj.style.display = "contents";
	}
}

function onhashchangedoc(evt) {
	anchor_update();
}

var sel_collapsed_on_mousedown = false;

function onmousedown_selstate(evt) {
	sel_collapsed_on_mousedown = getSelection().isCollapsed;
}

var svg_hilight = null;

function onmouseenter_eth(evt) {
	const obj = evt.target;

	if (svg_hilight !== null)
		svg_hilight.classList.remove("src-hilight");
	svg_hilight = null;

	let svg_rtr = document.getElementById("router-" + obj.d_router);
	for (const textobj of svg_rtr.getElementsByTagName("text")) {
		if (textobj.textContent == obj.d_iface) {
			let poly = textobj;
			while (poly.tagName != "polygon")
				poly = poly.previousElementSibling;

			svg_hilight = poly;
			poly.classList.add("src-hilight");
		}
	}
}

function onmouseleave_eth(evt) {
	if (svg_hilight !== null)
		svg_hilight.classList.remove("src-hilight");
	svg_hilight = null;
}

const eth_wellknown = {
	"ff:ff:ff:ff:ff:ff": "bcast",
	"01:80:c2:00:00:0e": "eth-link",
};

const mac_name_re = /^(.*) \((.*)\)$/;

function eth_pretty(htmlparent, csscls, macaddr) {
	var name;

	if (macaddr in jsdata["macmap"]) {
		name = jsdata["macmap"][macaddr];
		let m = name.match(mac_name_re);
		if (m) {
			if (m[2].startsWith(m[1]))
				name = m[2];
			let elem = create(htmlparent, "span", csscls, name);
			elem.title = macaddr;
			elem.d_router = m[1];
			elem.d_iface = m[2];
			elem.onmouseenter = onmouseenter_eth;
			elem.onmouseleave = onmouseleave_eth;
			return;
		}
	} else if (macaddr in eth_wellknown)
		name = eth_wellknown[macaddr];
	else if (macaddr.startsWith("01:00:5e:"))
		name = "v4mcast";
	else if (macaddr.startsWith("33:33:"))
		name = "v6mcast";
	else if (macaddr === "01:80:c2:00:00:14")
		name = "isis-mc";
	else
		name = macaddr;

	create(htmlparent, "span", csscls, name);
}

var pdmltree;

function pdml_add_field(htmlparent, field) {
	if (field.attributes["hide"])
		return;

	var htmlfield = document.createElement("div");
	var fdata = document.createElement("span");
	if ("showname" in field.attributes) {
		fdata.textContent = field.attributes["showname"].value;
	} else if ("show" in field.attributes) {
		fdata.textContent = field.attributes["show"].value;
	} else {
		fdata.textContent = "(unnamed)";
	}
	if ("name" in field.attributes && "value" in field.attributes) {
		fdata.title = field.attributes["name"].value + ": " +
			field.attributes["value"].value;
	}
	htmlfield.appendChild(fdata);
	htmlparent.appendChild(htmlfield);

	for (const childfield of field.children)
		pdml_add_field(htmlfield, childfield);
	return htmlfield;
}

function expand_proto(title) {
	var fields = title.nextSibling;

	if (fields.style.display == "none") {	
		fields.style.display = "block";
	} else {
		fields.style.display = "none";
	}
}

function onclick_pdml_dt(evt) {
	expand_proto(container_tag(evt.target, "dt"));
}

function pdml_add_proto(htmlparent, proto) {
	var title = document.createElement("dt");
	if ("showname" in proto.attributes) {
		title.textContent = proto.attributes["showname"].value;
	} else if ("show" in proto.attributes) {
		title.textContent = proto.attributes["show"].value;
	} else {
		title.textContent = "(?)";
	}
	title.onclick = onclick_pdml_dt;
	htmlparent.appendChild(title);

	var fields = document.createElement("dd");
	fields.style.display = "none";
	htmlparent.appendChild(fields);

	var pdml_raw_btn = create(title, "span", "pdml-raw", "‹R›");
	var pdml_raw = create(fields, "div", "pdml-raw", proto.outerHTML);

	pdml_raw.style.display = "none";
	pdml_raw_btn.onclick = function(evt) {
		evt.stopPropagation();
		if (pdml_raw.style.display == "none")
			pdml_raw.style.display = "block";
		else
			pdml_raw.style.display = "none";
	};


	for (const field of proto.children)
		pdml_add_field(fields, field);

	return title;
}

var pdml_decode;

function onclick_pkt(evt) {
	const pkt = container_class(evt.target, "pkt");
	const infopane = document.getElementById("infopane");
	const packet = pkt.obj.pdml;

	let htmlpacket = document.createElement("dl");
	htmlpacket.classList.add("pdml-root");

	let back_nav = document.createElement("dt");
	back_nav.classList.add("back-nav");
	back_nav.textContent = "‹ back to network diagram";
	back_nav.onclick = function () {
		pdml_decode.replaceChildren();
		infopane.children[0].style.display = "";
	};
	htmlpacket.appendChild(back_nav);

	var last_htmlproto;

	for (const proto of packet.children)
		last_htmlproto = pdml_add_proto(htmlpacket, proto);

	expand_proto(last_htmlproto);

	infopane.children[0].style.display = "none";
	pdml_decode.replaceChildren(htmlpacket);
	pdml_decode.style.display = "contents";
}

/* global pako:readonly */

function b64_inflate_json(b64data) {
	var bytearr = Uint8Array.from(atob(b64data), i => i.charCodeAt(0));
	var text = new TextDecoder().decode(pako.inflate(bytearr));
	return JSON.parse(text);
}

/*
 *
 */

var jsdata;
var ts_start;

function create(parent_, tagname, clsname, text = undefined) {
	var element;

	element = document.createElement(tagname);
	for (let cls of clsname.split(" "))
		if (cls !== "")
			element.classList.add(cls);
	if (text !== undefined)
		element.appendChild(document.createTextNode(text));
	parent_.appendChild(element);
	if (parent_.tagName.toLowerCase() == "div" && tagname == "span")
		parent_.append("\t");
	return element;
}

const mono_xrefs = new Set(["VDSXN-XE88Y", "SH01T-57BR4", "TCYNJ-TRV01", "TRN9Y-VYTR4"]);

/* global coverage_loc:readonly */

function uidspan_hover_hide_uid() {
	let hide_uid = hover_child.obj.data.uid;
	hover_clear();

	let opts = {...anchor_current};
	let cur_log = opts["log"].split("/");
	cur_log.push(`-u:${hide_uid}`);
	opts["log"] = cur_log.join("/");

	anchor_export(opts);
}

function uidspan_hover(elem) {
	let obj = elem.parentElement.obj;

	hover_child.obj = obj;
	hover_child.style.fontSize = "11pt";

	let uid_e = create(hover_child, "span", "uid", obj.data.uid);
	hover_child.appendChild(document.createTextNode(" "));

	let hide_uid_action = create(hover_child, "span", "action", "[hide]");
	hide_uid_action.onclick = uidspan_hover_hide_uid;

	if (obj.data.uid in xrefs) {
		for (const srcloc of xrefs[obj.data.uid]) {
			create(hover_child, "div", "", `${srcloc["file"]}:${srcloc["line"]} (${srcloc["binary"]})`);
		}
	} else {
		uid_e.classList.add("uid-unknown");
		create(hover_child, "div", "", "xref uid not found");
	}
}

function arg_hover(elem) {
	hover_child.classList.add("logarghover");
	create(hover_child, "div", "carg", elem.obj_carg);
	create(hover_child, "div", "cfmt", elem.obj_cfmt);
	create(hover_child, "div", "cout", `⇒ "${elem.obj_cout}"`);
}

const c_scan_re = /[[{(,)}\]"']/;
const c_str_re = /["'\\]/;
const c_fmt_re = /(?<!%)%(([0-9]+)\$)?([-#0 +'I]*)(([0-9]+|(\*[0-9]+\$)?)\.)?([0-9]+|(\*[0-9]+\$)?)?(hh|h|l|ll|L|q|j|z|Z|t)?([iouxXeEfFgGaAcCsSm]|[dp]([A-Z0-9]+[a-z]*)?)/g;

function c_arg_split(text) {
	let cur = "";
	let ret = new Array();
	let depth = 0;
	let pos;

	while ((pos = text.search(c_scan_re)) >= 0) {
		const ch = text[pos];
		if (pos)
			cur = cur + text.substr(0, pos);
		text = text.substr(pos + 1);

		if (ch == "," && depth == 0) {
			ret.push(cur.trim());
			cur = "";
			continue;
		}

		cur += ch;

		if (ch == "[" || ch == "(" || ch == "{")
			depth++;
		if (ch == "]" || ch == ")" || ch == "}")
			depth--;
		if (ch == "'" || ch == "\"") {
			while ((pos = text.search(c_str_re)) >= 0) {
				const cch = text[pos];

				if (cch == "\\") {
					cur = cur + text.substr(0, pos + 2);
					text = text.substr(pos + 2);
					continue;
				}
				cur = cur + text.substr(0, pos + 1);
				text = text.substr(pos + 1);
				if (cch == ch)
					break;
			}
		}
	}
	cur += text;
	if (cur.trim() != "")
		ret.push(cur.trim());
	return ret;
}

function load_log(timetable, obj, xrefs) {
	var row, logmeta, uidspan;

	row = create(timetable, "div", "logmsg");
	row.classList.add("prio-" + obj.data.prio);
	row.obj = obj;
	row.c_args = new Array();
	row.c_fmts = new Array();

	create(row, "span", "tstamp", (obj.ts - ts_start).toFixed(3));
	create(row, "span", "rtrname", obj.data.router);
	create(row, "span", "dmnname", obj.data.daemon);

	logmeta = create(row, "span", "logmeta");

	if (mono_xrefs.has(obj.data.uid))
		row.classList.add("mono");

	if (obj.data.uid in xrefs) {
		var srclocs = new Set();
		var srcloc;

		for (srcloc of xrefs[obj.data.uid]) {
			srclocs.add(srcloc["file"] + srcloc["line"]);
		}
		if (srclocs.size != 1) {
			uidspan = create(logmeta, "span", "uid uid-ambiguous", obj.data.uid);
			uidspan.title = "xref uid is ambiguous";
		} else {
			let xref_file = row.xref_file = srcloc["file"];
			let xref_line = row.xref_line = srcloc["line"];

			row.c_args = c_arg_split(xrefs[obj.data.uid][0].args);
			row.c_fmts = xrefs[obj.data.uid][0].fmtstring.matchAll(c_fmt_re).toArray();

			uidspan = create(logmeta, "a", "uid", obj.data.uid);
			/* uidspan.title = `${xref_file} line ${xref_line}`; */

			try {
				if (coverage_loc)
					uidspan.href = `${coverage_loc}/${xref_file}.gcov.html#L${xref_line}`;
			} catch (e) {
				/* ignore */
			}
		}
	} else {
		uidspan = create(logmeta, "span", "uid uid-unknown", obj.data.uid);
		uidspan.title = "xref uid not found";
		row.classList.add("mono");
	}
	logmeta.onmouseover = hover_mouseover;
	logmeta.onmouseout = hover_mouseout;
	logmeta.hover_handler = uidspan_hover;

	create(row, "span", "logprio", obj.data.prio);
	let logtext = create(row, "span", "logtext", "");

	var prev_e = obj.data.arghdrlen;
	let i = 0;
	for (let [s, e] of Object.values(obj.data.args)) {
		logtext.append(obj.data.text.substr(prev_e, s - prev_e));
		let s_arg = create(logtext, "span", "logarg", obj.data.text.substr(s, e - s));
		prev_e = e;

		if (row.c_fmts[i]) {
			s_arg.obj_cfmt = row.c_fmts[i][0];
			let j = i;
			if (row.c_fmts[i][2] !== undefined)
				j = parseInt(row.c_fmts[i][2]);
			s_arg.obj_carg = row.c_args[j];
			s_arg.obj_cout = obj.data.text.substr(s, e - s);

			s_arg.onmouseover = hover_mouseover;
			s_arg.onmouseout = hover_mouseout;
			s_arg.hover_handler = arg_hover;
		}
		i++;
	}
	logtext.append(obj.data.text.substr(prev_e));
}

function load_other(timetable, obj, xrefs) {
	let row = create(timetable, "div", "event");
	row.obj = obj;

	create(row, "span", "tstamp", (obj.ts - ts_start).toFixed(3));
	create(row, "span", "rtrname", obj.data.router || "");
	create(row, "span", "dmnname", obj.data.daemon || "");
	let textspan = create(row, "span", "eventtext");

	if (obj.data.type == "log_closed") {
		row.classList.add("event-log-closed");
		textspan.append("log connection closed");
	} else {
		row.classList.add("event-unknown");
		textspan.append(`unknown event: ${obj.data.type}`);
	}
}

const whitespace_re = /^([ \t]+)/;

/* NB: the fact that this is text-level mangling rather than parsing JSON is
 * absolutely intentional.  This being a test system, we need to
 *  (a) not modify the test target's output, in case it provides hints about
 *      something going wrong somewhere
 *  (b) deal with potentially malformed JSON (e.g. in FRR, a random call to
 *      vtysh_out() in the middle of outputting JSON data)
 */
function json_to_tree(textrow, text) {
	var lines = text.split("\n");
	var nest = new Array();
	var indent = new Array();

	if (text.endsWith("\n"))
		lines.pop();

	nest.unshift(create(textrow, "div", "cliouttext clijson"));
	indent.unshift("");

	while (lines.length > 0) {
		var line = lines.shift();
		var use_nest  = nest[0];

		while (!line.startsWith(indent[0])) {
			indent.shift();
			use_nest = nest.shift();
		}

		if (!line.endsWith("]") && !line.endsWith("],") && !line.endsWith("}") && !line.endsWith("},"))
			use_nest = nest[0];

		let cur_flex = create(use_nest, "div", "clijsonflex");
		create(cur_flex, "span", "clijsonitem", line);

		/* indent of *next* line! */
		let indent_m = whitespace_re.exec(lines[0]);
		if (indent_m && (line.endsWith("[") || line.endsWith("{"))) {
			let new_nest = create(nest[0], "div", "clijsonnest");
			new_nest.style.maxHeight = "fit-content";
			nest.unshift(new_nest);
			indent.unshift(indent_m[1]);

			let unshorten = create(cur_flex, "span", "cliunshorten");
			unshorten.style.display = "inline";
			let collapse = create(cur_flex, "span", "clicollapse");
			collapse.style.display = "inline";
			let shorten = create(cur_flex, "span", "clishorten");
			shorten.style.display = "none";

			for (let shorten_line of lines.slice(0, 10)) {
				if (!shorten_line.startsWith(indent[0]))
					break;
				shorten.append(shorten_line + " ");
			}

			cur_flex.do_collapse = function() {
				/* collapsed content with max-height: 0
				 * is still "present" for selecting &
				 * copypasting
				 */
				new_nest.style.maxHeight = "0";
				collapse.style.display = "none";
				unshorten.style.display = "none";
				shorten.style.display = "inline";
			};
			cur_flex.do_uncollapse = function() {
				new_nest.style.maxHeight = "fit-content";
				shorten.style.display = "none";
				unshorten.style.display = "inline";
				collapse.style.display = "inline";
			};

			shorten.onclick = function() {
				event.stopPropagation();
				cur_flex.do_uncollapse();
			};
			unshorten.onclick = function() {
				event.stopPropagation();
				cur_flex.do_collapse();
			};
			cur_flex.onclick = function() {
				event.stopPropagation();
				if (!getSelection().isCollapsed || !sel_collapsed_on_mousedown)
					return;
				if (new_nest.style.maxHeight != "fit-content") {
					cur_flex.do_uncollapse();
				} else {
					cur_flex.do_collapse();
				}
			};
			collapse.onclick = function() {
				event.stopPropagation();
				for (const child of new_nest.children) {
					if ("do_collapse" in child)
						child.do_collapse();
				}
			};
		}
	}
}

const vtysh_retcodes = {
	0: ["cmd-success", null],
	1: ["cmd-warning", "CMD_WARNING"],
	2: ["cmd-err", "CMD_ERR_NO_MATCH"],
	3: ["cmd-err", "CMD_ERR_AMBIGUOUS"],
	4: ["cmd-err", "CMD_ERR_INCOMPLETE"],
	5: ["cmd-err", "CMD_ERR_EXEED_ARGC_MAX"],
	6: ["cmd-err", "CMD_ERR_NOTHING_TODO"],
	/* 7 CMD_COMPLETE_FULL_MATCH should never be seen */
	/* 8 CMD_COMPLETE_MATCH should never be seen */
	/* 9 CMD_COMPLETE_LIST_MATCH should never be seen */
	10: ["cmd-success", "CMD_SUCCESS_DAEMON"],
	11: ["cmd-err", "CMD_ERR_NO_FILE"],
	/* 12 - CMD_SUSPEND should never be seen */
	13: ["cmd-warning", "CMD_WARNING_CONFIG_FAILED"],
	14: ["cmd-success", "CMD_NOT_MY_INSTANCE"],
	15: ["cmd-err", "CMD_NO_LEVEL_UP"],
	16: ["cmd-err", "CMD_ERR_NO_DAEMON"],
};

function load_vtysh(timetable, obj) {
	var row;
	var prev_cmds = timetable.querySelectorAll("div.clicmd");

	row = create(timetable, "div", "clicmd");
	row.obj = obj;

	create(row, "span", "tstamp", (obj.ts - ts_start).toFixed(3));
	create(row, "span", "rtrname", obj.data.router);
	create(row, "span", "dmnname", obj.data.daemon);
	let cmdspan = create(row, "span", "clicmdtext");
	create(cmdspan, "span", "", obj.data.command);

	if (obj.data.retcode in vtysh_retcodes) {
		const [cls, name] = vtysh_retcodes[obj.data.retcode];
		if (name !== null)
			create(cmdspan, "span", "cmd-ret", " " + name);
		row.classList.add(cls);
	} else {
		create(cmdspan, "span", "cmd-ret", ` unknown retcode ${obj.data.retcode}`);
		row.classList.add("cmd-err");
	}

	if (obj.data.text) {
		row.classList.add("cli-has-out");
		row.onclick = onclickclicmd;

		var textrow = create(timetable, "div", "cliout");
		textrow.obj = obj;

		var jsonp = null;
		try {
			jsonp = JSON.parse(obj.data.text);
		} catch (e) {
			/* ignore */
		}
		if (jsonp !== null) {
			let text = JSON.stringify(jsonp, null, "  ");
			json_to_tree(textrow, text);
		} else
			create(textrow, "span", "cliouttext", obj.data.text);

		if (prev_cmds.length > 0) {
			var last_cmd = prev_cmds[prev_cmds.length - 1];
			if (last_cmd.obj.data.text == obj.data.text)
				row.classList.add("cli-same");
		}
	}
}

function load_protocols(obj, row, protodefs, protos) {
	while (protos.length > 0) {
		var proto = protos.shift();
		var protoname = proto.getAttribute("name");

		if (!(protoname in protodefs)) {
			console.warn("packet %s: no HTML display for protocol %s", obj.data.frame_num, protoname);
			break;
		}
		if (protodefs[protoname] === null)
			continue;

		try {
			if (protodefs[protoname](obj, row, proto, protos))
				continue;
		} catch (exc) {
			console.warn("packet %s: HTML decode for %s threw exception", obj.data.frame_num, protoname, exc);
		}
		break;
	}
}

function pdml_get(item, key, idx = 0) {
	var iter = pdmltree.evaluate("field[@name='"+key+"']", item, null, XPathResult.ORDERED_NODE_ITERATOR_TYPE);
	var result;

	while (idx >= 0) {
		result = iter.iterateNext();
		if (result === null)
			return null;
		idx--;
	}
	return result;
}

function pdml_get_attr(item, key, attr = "show", idx = 0) {
	var result = pdml_get(item, key, idx);
	return result === null ? null : result.getAttribute(attr);
}
function pdml_get_attr_bool(item, key, attr = "show", idx = 0) {
	return ["1", "True", "true"].includes(pdml_get_attr(item, key, attr, idx));
}

function pdml_get_value(item, key, idx = 0) {
	var result = pdml_get(item, key, idx);

	if (result === null)
		return null;
	return parseInt(result.getAttribute("value"), 16);
}

function strip_colon(text) {
	return text.split(": ").slice(1).join(": ");
}

const mld_short_recordtypes = {
	1: "IN",
	2: "EX",
	3: "→IN",
	4: "→EX",
	5: "+S",
	6: "-S",
};
const isis_types = {
	15: "IIH L1",
	16: "IIH L2",
	17: "IIH PtP",

	10: "LSP FS",
	18: "LSP L1",
	20: "LSP L2",

	24: "CSNP L1",
	25: "CSNP L2",
	26: "PSNP L1",
	27: "PSNP L2",
};

const protocols = {
	"geninfo": null,
	"frame": null,
	"pkt_comment":  function (obj, row, proto, protos) {
		row.classList.add("assert-match");

		var row2 = document.createElement("div");
		row2.classList.add("pkt");
		create(row2, "span", "assert-match-item", pdml_get_attr(proto, "frame.comment"));
		row.after(row2);
		return true;
	},

	"eth": function (obj, row, proto, protos) {
		var col = create(row, "span", "pktcol p-eth");

		eth_pretty(col, "pktsub p-eth-src", pdml_get_attr(proto, "eth.src"));
		create(col, "span", "pktsub p-eth-arr", "→");
		eth_pretty(col, "pktsub p-eth-dst", pdml_get_attr(proto, "eth.dst"));
		return true;
	},
	"llc": function (obj, row, proto, protos) {
		return true;
	},

	"arp": function (obj, row, proto, protos) {
		create(row, "span", "pktcol l-3 p-arp last", "ARP");
		return false;
	},
	"ip": function (obj, row, proto, protos) {
		create(row, "span", "pktcol l-3 p-ipv4", "IPv4");
		return true;
	},
	"ipv6": function (obj, row, proto, protos) {
		if (pdml_get_attr(proto, "ipv6.src").startsWith("fe80::"))
			create(row, "span", "pktcol l-3 p-ipv6", "IPv6 LL");
		else
			create(row, "span", "pktcol l-3 p-ipv6", "IPv6");
		return true;
	},

	"icmpv6": function (obj, row, proto, protos) {
		let text;
		let pname = "ICMPv6";
		let type_num = pdml_get_value(proto, "icmpv6.type");

		if ([130, 131, 132, 143].includes(type_num))
			pname = "MLD";

		if (type_num == 143) {
			let items = new Array;
			for (const record of proto.querySelectorAll("field[name='icmpv6.mldr.mar']")) {
				let raddr = pdml_get_attr(record, "icmpv6.mldr.mar.multicast_address");
				let rtype = pdml_get_attr(record, "icmpv6.mldr.mar.record_type");
				items.push(mld_short_recordtypes[rtype] + "(" + raddr + ")");
			}
			text = "v2 report: " + items.join(", ");
		} else {
			let type = pdml_get_attr(proto, "icmpv6.type", "showname");
			text = type.split(": ").slice(1).join(": ");
		}
		create(row, "span", "pktcol l-4 p-icmpv6", pname);
		create(row, "span", "pktcol l-5 detail last", text);
		return false;
	},
	"igmp": function (obj, row, proto, protos) {
		let type = pdml_get_attr(proto, "igmp.type", "showname");
		let text = type.split(": ").slice(1).join(": ");

		create(row, "span", "pktcol l-4 p-igmp", `IGMPv${pdml_get_attr(proto, "igmp.version")}`);
		create(row, "span", "pktcol l-5 detail last", text);
		return false;
	},
	"udp": function (obj, row, proto, protos) {
		create(row, "span", "pktcol l-4 p-udp last", `UDP ${pdml_get_attr(proto, "udp.srcport")} → ${pdml_get_attr(proto, "udp.dstport")}`);
		return false;
	},
	"tcp": function (obj, row, proto, protos) {
		if (proto.nextElementSibling)
			return true;

		let elem = create(row, "span", "pktcol l-4 p-tcp last", `TCP ${pdml_get_attr(proto, "tcp.srcport")} → ${pdml_get_attr(proto, "tcp.dstport")}`);

		let flags = pdml_get(proto, "tcp.flags");
		let flag_arr = new Array();
		if (pdml_get_attr_bool(flags, "tcp.flags.syn"))
			flag_arr.push("SYN");
		if (pdml_get_attr_bool(flags, "tcp.flags.fin"))
			flag_arr.push("FIN");
		if (pdml_get_attr_bool(flags, "tcp.flags.reset"))
			flag_arr.push("RST");

		if (flag_arr.length) {
			if (pdml_get_attr_bool(flags, "tcp.flags.ack"))
				flag_arr.push("ACK");

			elem.textContent += " [" + flag_arr.join(", ") + "]";
			for (let flag of flag_arr)
				elem.classList.add("p-tcp-" + flag.toLowerCase());
		}
		return false;
	},

	"pim": function (obj, row, proto, protos) {
		let text;
		let type = pdml_get_attr(proto, "pim.type", "showname").split(": ").slice(1).join(": ");
		let type_num = pdml_get_value(proto, "pim.type");

		if (type_num == 3) {
			let items = new Array;
			for (const group of proto.querySelectorAll("field[name='pim.group_set']")) {
				items.push(pdml_get_attr(group, "pim.group_ip6") || pdml_get_attr(group, "pim.group"));
			}
			text = "J/P: " + items.join(", ");
		} else {
			text = type;
		}
		create(row, "span", "pktcol l-4 p-pim", "PIM");
		create(row, "span", "pktcol l-5 p-pim detail last", text);
		return false;
	},
	"ospf": function (obj, row, proto, protos) {
		let text;
		let header = pdml_get(proto, "ospf.header");

		let type = pdml_get_attr(header, "ospf.msg", "showname").split(": ").slice(1).join(": ");
		let type_num = pdml_get_value(header, "ospf.msg");
		let area = pdml_get_attr(header, "ospf.area_id", "show");

		if (type_num == 1) {
			let hello = pdml_get(proto, "ospf.hello");
			let prio = pdml_get_attr(hello, "ospf.hello.router_priority", "show");
			let dr = pdml_get_attr(hello, "ospf.hello.designated_router", "show");
			text = `Hello (prio=${prio}, DR=${dr})`;
		} else if (type_num == 4) {
			const braces = /\((.*)\)/;
			const maxitems = 3;

			const lsupd = pdml_get(proto, "");
			let items = new Array;
			for (const lsa of lsupd.querySelectorAll("field[name='']")) {
				if (lsa.parentElement != lsupd)
					continue;

				let name = lsa.getAttribute("show");
				let match = braces.exec(name);
				if (match)
					name = match[1];
				name = name.replace("Inter-Area-Prefix", "IAP");
				name = name.replace("Inter-Area-Router", "IAR");
				name = name.replace("Inter-Area-", "IA-");
				name = name.replace("Intra-Area-", "");
				items.push(name);
			}
			if (items.length > maxitems) {
				var cut = items.length - maxitems;

				items = items.slice(0, maxitems);
				items.push(`…+${cut}`);
			}
			text = `LS Update (${items.join(", ")})`;
		} else {
			text = type;
		}
		if (area != "0.0.0.0")
			text = `(A ${area}) ${text}`;

		create(row, "span", "pktcol l-4 p-ospf", "OSPF");
		create(row, "span", "pktcol l-5 p-ospf detail last", text);
		return false;
	},
	"bgp": function (obj, row, proto, protos) {
		const rex = /^.*: (.*?) Message.*/;

		var items = new Array;
		var idx = 0;

		while (proto && idx++ < 6) {
			let msgtype = pdml_get_attr(proto, "bgp.type", "showname");
			let msglen = pdml_get_value(proto, "bgp.length");

			let m = msgtype.match(rex);
			if (!m) {
				items.push(msgtype);
				proto = proto.nextElementSibling;
				continue;
			}

			msgtype = m[1];
			if (msgtype == "NOTIFICATION") {
				let major = strip_colon(pdml_get_attr(proto, "bgp.notify.major_error", "showname"));
				let minor = strip_colon(proto.lastElementChild.getAttribute("showname"));
				msgtype = `NOTIFY ${major}/${minor}`;
			} else if (msgtype == "UPDATE" && msglen == 23) {
				msgtype = "EOR";
			} else if (msgtype == "UPDATE") {
				let subitems = new Array;

				for (const nlri of proto.querySelectorAll("field[name='bgp.update.nlri']")) {
					subitems.push(pdml_get_attr(nlri, ""));
				}
				for (const nlri of proto.querySelectorAll("field[name='bgp.update.path_attribute.mp_reach_nlri']")) {
					for (const item of nlri.querySelectorAll("field[name='']")) {
						subitems.push(item.getAttribute("show"));
					}
				}
				msgtype = "UPDATE [" + subitems.join(", ") + "]";
			}
			items.push(msgtype);
			proto = proto.nextElementSibling;
		}
		create(row, "span", "pktcol l-4 p-bgp", "BGP");
		create(row, "span", "pktcol l-5 p-bgp detail last", items.join(", "));
		return false;
	},
	"isis": function (obj, row, proto, protos) {
		let pkttype = pdml_get_value(proto, "isis.type");

		create(row, "span", "pktcol l-3 p-isis", isis_types[pkttype] || "??");
		return true;
	},
	"isis.hello": function (obj, row, proto, protos) {
		var text;
		let sysid = pdml_get_attr(proto, "isis.hello.source_id", "show");

		text = `${sysid}`;
		var nbrs = new Array;
		for (const neighbor of proto.querySelectorAll("field[name='isis.hello.is_neighbor']"))
			nbrs.push(neighbor.getAttribute("show"));
		if (nbrs.length > 0)
			text = text + ` [nbrs: ${nbrs.join(", ")}]`;

		create(row, "span", "pktcol l-4 p-isis-hello last", text);
		return false;
	},
	"isis.lsp": function (obj, row, proto, protos) {
		let lspid = pdml_get_attr(proto, "isis.lsp.lsp_id", "show");
		let seqno = pdml_get_value(proto, "isis.lsp.sequence_number");

		var text = `${lspid} seq#${seqno}`;
		var prefixes = new Array;

		for (const tlv of proto.children) {
			if (tlv.getAttribute("name") !== "")
				continue;

			let type = pdml_get_value(tlv, "isis.lsp.clv.type");
			if (type !== 135 && type !== 235 && type !== 236 && type !== 237)
				continue;
			for (const subtlv of tlv.children) {
				if (subtlv.getAttribute("name") !== "")
					continue;

				const prefix = strip_colon(subtlv.getAttribute("show"));
				if (prefixes.indexOf(prefix) == -1)
					prefixes.push(prefix);
			}
		}
		if (prefixes.length > 0)
			text = `${text} [${prefixes.join(", ")}]`;

		create(row, "span", "pktcol l-4 p-isis-lsp last", text);
		return false;
	},
};

function load_packet(timetable, obj, pdmltree) {
	var row, pdml;

	pdml = pdmltree.evaluate(
		"packet[proto[@name='geninfo']/field[@name='num'][@show='" + obj.data.frame_num + "']]",
		pdmltree.children[0], null, XPathResult.ANY_UNORDERED_NODE_TYPE).singleNodeValue;

	if (!pdml) {
		console.error("Could not find frame number %s in PDML", obj.data.frame_num);
		return;
	}
	obj.pdml = pdml;

	row = create(timetable, "div", "pkt");
	row.obj = obj;
	row.onclick = onclick_pkt;

	create(row, "span", "pktcol tstamp", (obj.ts - ts_start).toFixed(3));
	create(row, "span", "pktcol ifname", obj.data.iface);

	load_protocols(obj, row, protocols, Array.from(pdml.children));
}

function pullup(arr, item) {
	var pos = arr.indexOf(item);
	if (pos < 0)
		return;
	arr.splice(pos, 1);
	arr.unshift(item);
}

var cfg_selected = null;
var cfg_wrap, cfg_text, cfg_dl;

function cfg_click(evt) {
	evt.stopPropagation();
	var item = evt.target;

	if (cfg_selected !== null)
		cfg_selected.classList.remove("active");

	cfg_selected = item;
	if (cfg_selected === null || item._config === null) {
		cfg_selected = null;
		cfg_wrap.style.display = "none";
		cfg_text.innerText = "";
		cfg_dl.href = "data:";
		return;
	}
	cfg_selected.classList.add("active");
	cfg_wrap.style.display = "block";
	cfg_text.innerText = item._config;
	cfg_dl.download = `${item._router}_${item._daemon}.conf`;
	cfg_dl.href = "data:text/plain;charset=UTF-8," + encodeURIComponent(item._config);
}

function load_configs(configs) {
	var linklist = document.querySelector("div#main > ul");

	var cfg_root = document.createElement("dl");
	cfg_root.classList.add("configs");
	linklist.after(cfg_root);

	cfg_wrap = document.createElement("div");
	cfg_wrap.classList.add("config");
	cfg_wrap.style.display = "none";
	cfg_root.after(cfg_wrap);

	var cfg_buttons = create(cfg_wrap, "div", "cfg-buttons");
	cfg_dl = create(cfg_buttons, "a", "cfg-dl", "▽ download");

	var cfg_close = create(cfg_buttons, "span", "cfg-close", "☒ close");
	cfg_close.clickable = true;
	cfg_close._config = null;
	cfg_close.onclick = cfg_click;

	cfg_text = create(cfg_wrap, "code", "config");

	var daemons = new Array();

	for (let rtr of Object.keys(configs))
		daemons = daemons.concat(Object.keys(configs[rtr]));

	daemons = new Array(...new Set(daemons));
	daemons.sort();
	pullup(daemons, "staticd");
	pullup(daemons, "zebra");

	cfg_root.style.gridTemplateColumns = `repeat(${daemons.length + 1}, max-content)`;

	for (let rtr of Object.keys(configs).sort()) {
		create(cfg_root, "dt", "", rtr);

		for (const daemon of daemons) {
			if (daemon in configs[rtr]) {
				var item = create(cfg_root, "dd", "cfg-present", `${daemon}.conf`);
				item.clickable = true;
				item._router = rtr;
				item._daemon = daemon;
				item._config = configs[rtr][daemon];
				item.onclick = cfg_click;
			} else
				create(cfg_root, "dd", "cfg-absent", "");
		}
	}
}

var xrefs;

/* global data:readonly */
/* exported init */
function init() {
	window.addEventListener("hashchange", onhashchangedoc);
	document.onmousedown = onmousedown_selstate;

	const infopane = document.getElementById("infopane");
	pdml_decode = create(infopane, "div", "pdml_decode");
	pdml_decode.style.display = "none";

	jsdata = b64_inflate_json(data);
	ts_start = jsdata.ts_start;

	load_configs(jsdata.configs);

	var parser = new DOMParser();
	pdmltree = parser.parseFromString(jsdata.pdml, "application/xml");

	var timetable;
	var ts_end = parseFloat("-Infinity");
	var item_idx = -1;
	xrefs = ("xrefs" in jsdata) ? jsdata["xrefs"] : new Object();

	for (const idx in jsdata.timed) {
		var obj = jsdata.timed[idx];
		obj.idx = idx;

		while (obj.ts > ts_end && item_idx < jsdata.items.length) {
			item_idx++;
			ts_end = jsdata.items[item_idx].ts_end;
			timetable = document.getElementById("i" + item_idx + "d").getElementsByClassName("timetable")[0];
		}

		if (obj.data.type == "packet")
			load_packet(timetable, obj, pdmltree);
		else if (obj.data.type == "log")
			load_log(timetable, obj, xrefs);
		else if (obj.data.type == "vtysh")
			load_vtysh(timetable, obj);
		else
			load_other(timetable, obj);
	}

	anchor_update();
}

/* exported anchorclick */
function anchorclick(evt) {
	evt.stopPropagation();

	var targetanchor = evt.target.href;
	targetanchor = targetanchor.substr(targetanchor.indexOf("#") + 1);

	if (anchor_active !== null) {
		anchor_active.classList.remove("active");
	}
	anchor_active = null;

	let anchored = document.getElementById(targetanchor);
	console.log("anchor-click", targetanchor, anchored);
	if (anchored) {
		anchor_active = anchored;
		if (anchored !== prev_anchor)
			anchored.scrollIntoView();
		anchor_active.classList.add("active");
	}

	anchor_export(anchor_current);
	return false;
}
