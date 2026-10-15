// Luxon mínimo: lo justo que usa el nodo del parser (n8n expone $now como DateTime de Luxon).
const DIAS = ['lunes','martes','miércoles','jueves','viernes','sábado','domingo'];
class DT {
  constructor(d) { this.d = new Date(d); }
  static fromISO(s) { return new DT(s + (s.length === 10 ? 'T00:00:00' : '')); }
  get year() { return this.d.getFullYear(); }
  get month() { return this.d.getMonth() + 1; }
  get day() { return this.d.getDate(); }
  get weekday() { return this.d.getDay() === 0 ? 7 : this.d.getDay(); }
  get ts() { return this.d.getTime(); }
  startOf() { const x = new Date(this.d); x.setHours(0,0,0,0); return new DT(x); }
  endOf() { const x = new Date(this.d); x.setHours(23,59,59,999); return new DT(x); }
  plus(o = {}) { const x = new Date(this.d);
    if (o.days) x.setDate(x.getDate() + o.days);
    if (o.weeks) x.setDate(x.getDate() + o.weeks * 7);
    if (o.months) x.setMonth(x.getMonth() + o.months);
    if (o.years) x.setFullYear(x.getFullYear() + o.years);
    return new DT(x); }
  minus(o = {}) { const n = {}; for (const k in o) n[k] = -o[k]; return this.plus(n); }
  set(o = {}) { const x = new Date(this.d);
    if (o.year !== undefined) x.setFullYear(o.year);
    if (o.month !== undefined) x.setMonth(o.month - 1);
    if (o.day !== undefined) x.setDate(o.day);
    return new DT(x); }
  setLocale() { return this; }
  toISODate() { const p = n => String(n).padStart(2, '0');
    return `${this.year}-${p(this.month)}-${p(this.day)}`; }
  toFormat(f) { const p = n => String(n).padStart(2, '0');
    return f.replace('yyyy', this.year).replace('MM', p(this.month))
            .replace('dd', p(this.day)).replace('cccc', DIAS[this.weekday - 1]); }
  diff(otra, unidad) { const ms = this.d - otra.d;
    const div = { days: 86400000, hours: 3600000, minutes: 60000 }[unidad] || 1;
    return { as: () => ms / div, [unidad]: ms / div }; }
  hasSame(otra, u) { return u === 'day' ? this.toISODate() === otra.toISODate() : this.year === otra.year; }
  valueOf() { return this.d.getTime(); }
}
module.exports = { DateTime: { fromISO: DT.fromISO, now: () => new DT(Date.now()) }, DT };
