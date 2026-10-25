import { texts } from "./texts";

type Labels = { industry: (key: string) => string };

const t = texts.phrases;
const direction = (value: string) => texts.directions[value] ?? value;
const subject = (value: string) => texts.subjects[value] ?? value;
const product = (value: string) => texts.products[value.replace(/ /g, "_")] ?? value;
const role = (value: string) => texts.roles[value] ?? value;

function translate(text: string, rules: [RegExp, (...groups: string[]) => string][]) {
  if (t.fixed[text]) return t.fixed[text];
  for (const [pattern, render] of rules) {
    const match = text.match(pattern);
    if (match) return render(...match.slice(1));
  }
  return text;
}

function memberTrait(what: string) {
  if (what === "are in customs (FTS) data") return t.membersInCustoms;
  const trade = what.match(/^trade with (.+)$/);
  if (trade) return t.membersTradeWith(trade[1]);
  const use = what.match(/^use (.+)$/);
  if (use) return t.membersUse(product(use[1]));
  const region = what.match(/^are registered in (.+)$/);
  if (region) return t.membersRegistered(region[1]);
  return what;
}

export function roleBasis(text: string) {
  return translate(text, [
    [/^main activity (\S+) is holding or head office management$/, (okved) => t.holdingBasis(okved)],
    [/^main activity (\S+) is real estate$/, (okved) => t.realEstateBasis(okved)],
    [/^(\d+%) of its intra-group flow is received from members$/, (share) => t.receivesShare(share)],
    [/^(\d+%) of its intra-group flow is paid to members$/, (share) => t.paysShare(share)],
  ]);
}

export function reason(text: string, labels: Labels) {
  return translate(text, [
    [/^main activity: (\S+)$/, (okved) => t.mainActivity(okved)],
    [/^typical driver for industry (\S+)$/, (key) => t.typicalDriver(labels.industry(key))],
    [/^headcount (.+)$/, (staff) => t.headcount(staff)],
    [/^(\d+%) of group revenue is in industry (\S+)$/, (share, key) => t.groupRevenueIn(share, labels.industry(key))],
    [/^(\d+) other group member\(s\) (.+) \((\d+%) of the rest of group revenue\), largest (\S+)$/,
      (count, what, share, lead) => t.otherMembers(count, memberTrait(what), share, lead)],
    [/^(\d+%) of (company|group) (incoming|outgoing) payments involve industry (\S+)$/,
      (share, scope, dir, key) => t.paymentsInvolve(share, direction(dir), subject(scope), labels.industry(key))],
  ]);
}

export function claim(text: string, labels: Labels) {
  return translate(text, [
    [/^(Company|Group): (\d+%) of (incoming|outgoing) payments outside the group (?:go to|come from) companies in industry (\S+): (likely suppliers or contractors|likely customers)$/,
      (who, share, dir, key, kind) => t.flowIndustry(subject(who), share, direction(dir), labels.industry(key),
        kind === "likely customers" ? t.likelyCustomers : t.likelySuppliers)],
    [/^(Company|Group): one counterparty accounts for (\d+%) of (incoming|outgoing) payments outside the group: concentration risk$/,
      (who, share, dir) => t.concentration(subject(who), share, direction(dir))],
    [/^Role inside the group: (\S+) \((.+)\)$/, (name, basis) => t.roleInGroup(role(name), roleBasis(basis))],
    [/^Shares (\d+) related person\(s\) with (\S+) outside its group: possible business link$/,
      (count, uid) => t.sharedPersons(count, uid)],
  ]);
}

export function gap(text: string) {
  return translate(text, [
    [/^only (\d+%) of (incoming|outgoing) amount has a known counterparty profile$/,
      (share, dir) => t.knownCounterparty(share, direction(dir))],
  ]);
}

export const titleCase = (value: string) =>
  value.toLowerCase().replace(/(^|[\s-])(\S)/g, (_, sep: string, ch: string) => sep + ch.toUpperCase());

export function factorLabel(factor: string, labels: Labels) {
  if (texts.factorNames[factor]) return texts.factorNames[factor];
  const [kind, ...rest] = factor.split(":");
  const value = rest.join(":");
  if (kind === "industry") return `${texts.factorKinds.industry}: ${labels.industry(value)}`;
  if (kind === "country") return `${texts.factorKinds.country}: ${titleCase(value)}`;
  if (kind in texts.factorKinds) return `${texts.factorKinds[kind]}: ${value}`;
  return factor;
}

export const paymentRoles = new Set(["internal_supplier", "internal_buyer", "operating_company"]);
