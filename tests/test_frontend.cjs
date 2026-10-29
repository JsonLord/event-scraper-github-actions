const fs = require('fs'), vm = require('vm'), assert = require('assert');
const html = fs.readFileSync('web/index.html','utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
new vm.Script(script); // All frontend JavaScript must parse.
const functions = ['berlinClock', 'eventIsPast', 'safeLink', 'isoDate', 'icsDateStamp', 'matchesSearch','freshEvidence','priceRank','icsEscape','buildICS'].map(name => {
  const start=script.indexOf('  function '+name+'(');
  const end=script.indexOf('\n  }',start)+4;
  assert(start>=0 && end>start); return script.slice(start,end);
}).join('\n');
const c = {Intl, Date, URL, sourceName: () => "fixture source"};vm.createContext(c);vm.runInContext(functions,c);
// Berlin is already on the next day while UTC is still October 17.
const now = new Date('2026-10-17T22:30:00Z');
assert(c.eventIsPast({date:'2026-10-17',time:''}, now));
assert(!c.eventIsPast({date:'2026-10-18',time:''}, now));
assert(c.eventIsPast({date:'2026-10-18',time:'00:15'},now));
assert(!c.eventIsPast({date:'2026-10-18',time:'19:00'},now));
assert(!c.safeLink('javascript:alert(1)'));assert(c.safeLink('https://example.org/show'));
assert(c.icsDateStamp({date:'2026-10-18',time:'19:00'}).start.includes('20261018'));
assert(script.includes('ev.free_admission_confirmed !== true'));
console.log('Frontend syntax, Berlin midnight, unknown time, safe links, ICS: passed');

assert(c.matchesSearch({title:"A show", matched_categories:["theater"]},"THEATER"));
assert(!c.matchesSearch({title:"A show", matched_categories:["theater"]},"no-such-category"));

const currentStamp = new Date().toISOString();
assert(c.freshEvidence({observed_at:currentStamp},"status",12));
assert(!c.freshEvidence({observed_at:currentStamp,claim_expires_at:"2000-01-01T00:00:00Z"},"status",12));
assert(c.priceRank({price:12,observed_at:currentStamp,claim_expires_at:"2000-01-01T00:00:00Z"})===Infinity);

const expiredCalendar = c.buildICS([{title:"A show",date:"2026-10-18",time:"19:00",venue:"Berlin hall",description:"Student tickets €12",observed_at:currentStamp,claim_expires_at:"2000-01-01T00:00:00Z"}]);
assert(expiredCalendar.includes("BEGIN:VEVENT"));
assert(expiredCalendar.includes("Pilot evidence expired"));
assert(!expiredCalendar.includes("Student tickets"));
