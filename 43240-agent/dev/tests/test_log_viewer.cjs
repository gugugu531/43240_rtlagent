// Run from any directory: node dev/tests/test_log_viewer.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, '../tools/log_viewer.html'), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
new vm.Script(script);
const parser = vm.runInNewContext(script.split('// Local file indexing')[0] + '\nTraceParser;');
const parse = rows => parser.parse(rows.map(e => JSON.stringify(e)).join('\n'));

const events = [
  {tool:'run', event:'metadata', run_id:'r1', workflow:{name:'repair_loop'}},
  {tool:'node', event:'started', execution_id:'e001', component:{name:'generate'}, elapsed_s:0},
  {tool:'llm', event:'started', execution_id:'e001', call_id:'m001'},
  {tool:'llm', event:'failed', execution_id:'e001', call_id:'m001', kind:'timeout'},
  {tool:'node', event:'failed', execution_id:'e001', component:{name:'generate'}},
  {tool:'node', event:'started', execution_id:'e002', component:{name:'lint'}},
  {tool:'workflow', event:'check_started', execution_id:'e002', check_id:'k001', kind:'lint'},
  {tool:'lint', event:'result', execution_id:'e002', check_id:'k001', status:'passed'},
  {tool:'lint', event:'result', execution_id:'e002', check_id:'k002', status:'passed', details:{executed:false,reused_from_check_id:'k001'}},
  {tool:'node', event:'succeeded', execution_id:'e002', component:{name:'lint'}},
  {tool:'node', event:'started', execution_id:'e003', component:{name:'blocked'}, elapsed_s:0},
  {tool:'llm', event:'started', execution_id:'e003', call_id:'m002'},
  {tool:'supervisor', event:'result', status:'interrupted', stop_reason:'sigterm'},
];
const run=parser.build(parse(events).events);
assert.equal(run.workflow,'repair_loop');
assert.equal(run.status,'interrupted');
assert.equal(run.rows.filter(r=>r.kind==='node').length,3);
assert.equal(run.rows.filter(r=>r.kind==='llm').length,2);
assert.equal(run.rows.filter(r=>r.id==='check:k001').length,1);
assert.equal(run.rows.find(r=>r.id==='llm:m001').status,'error');
assert.equal(run.rows.find(r=>r.id==='llm:m002').status,'unfinished');
assert.equal(run.rows.find(r=>r.id==='node:e003').elapsed,undefined);
assert.equal(run.rows.find(r=>r.id==='check:k002').last.details.executed,false);
assert.equal(run.rows.find(r=>r.id==='llm:m001').depth,1);

const partial=parser.parse('\uFEFF'+JSON.stringify(events[0])+'\n{"broken":\nnull\n[]\n');
assert.equal(partial.events.length,1);
assert.equal(partial.warnings.length,3);
assert.equal(parser.build(parser.parse('').events).status,'unfinished');
assert.equal(parser.parse('').warnings.length,1);
const stopped=parser.build(parse([{tool:'agent',event:'done',status:'stopped'}, {tool:'supervisor',status:'completed'}]).events);
assert.equal(stopped.status,'stopped');
const baseline=parser.build(parse([{tool:'baseline_meta'},{tool:'llm',tokens_out:20}]).events);
assert.equal(baseline.rows.filter(r=>r.kind==='llm').length,1);
assert.equal(baseline.status,'unknown');
const nested=parser.build(parse([
  {tool:'node',execution_id:'e1',parent_execution_id:'e2',status:'started'},
  {tool:'node',execution_id:'e2',parent_execution_id:'e1',status:'started'},
]).events);
assert.equal(nested.rows.length,3,'malformed parent cycles must not hang');
const compact=parser.build(parse([
  {tool:'node',event:'started',execution_id:'e1',component:{name:'rtl_generate'},input:{task_id:'t'}},
  {tool:'node',event:'started',execution_id:'e2',parent_execution_id:'e1',component:{name:'inner'}},
  {tool:'node',event:'succeeded',execution_id:'e2',elapsed_s:0.1,output:null},
  {tool:'node',event:'succeeded',execution_id:'e1',elapsed_s:0.5,output:{call_id:'m001'}},
]).events);
const outer=compact.rows.find(r=>r.id==='node:e1');
assert.equal(outer.title,'rtl_generate','name comes from the started event');
assert.equal(outer.status,'succeeded');
assert.equal(outer.elapsed,0.5);
assert.equal(compact.rows.find(r=>r.id==='node:e2').parent,'node:e1','end events keep the started parent');
console.log('PASS: syntax, grouped calls, nesting, reuse, interruptions, malformed/empty traces, baseline, workflow status, compact node events');
