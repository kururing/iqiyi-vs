// Run: node test-ui-fit.cjs
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync(`${__dirname}/ui-engine.js`, "utf8");
const code = source.slice(source.indexOf("  function fitCompact("), source.indexOf("  function walk("));
const context = vm.createContext({window: {getComputedStyle: () => ({fontSize: "16px"})}});
vm.runInContext(code, context);
function label(width, height) {
  return {nodeType: 1, childElementCount: 0, clientWidth: width, clientHeight: height,
    scrollWidth: 150, scrollHeight: 20, innerText: "Quay lại đầu trang", style: {},
    setAttribute(key, value) { this[key] = value; }};
}
const hidden = label(0, 0);
context.fitCompact(hidden);
assert.deepEqual(hidden.style, {});
assert.equal(hidden["data-iqiyi-vi-fit"], undefined);
const visible = label(80, 20);
context.fitCompact(visible);
assert.equal(visible.style.whiteSpace, "nowrap");
assert.equal(visible.style.overflow, "hidden");
assert.equal(visible.style.textOverflow, "ellipsis");
assert.equal(visible.style.overflowWrap, "normal");
assert.equal(visible.title, visible.innerText);
assert.equal(fs.readFileSync(`${__dirname}/ext/content.js`, "utf8").replace(/\r\n/g, "\n"), source.replace(/\r\n/g, "\n"));
console.log("PASS: hidden tooltips untouched, compact labels stay on one line, full title preserved, extension sync");

// Badge translation must preserve the native absolute overlay; relative positioning shrinks flex posters.
assert(!source.includes("{position:relative!important;overflow:hidden!important;}"));
