// 8 validated categorical hues (see the app's data-viz palette reference) exposed
// as CSS custom properties (`--asn-0`..`--asn-7` in styles.css) so light/dark
// swap declaratively. ASNs are hashed to a slot index -- with more than 8
// distinct ASNs visible at once, some will share a slot; the printed "AS12345"
// label (not color) remains the ground truth for identity.
const ASN_COLOR_SLOTS = 8;

export function asnColorVar(asn: number): string {
  let h = asn ^ (asn >>> 16);
  h = Math.imul(h, 0x45d9f3b);
  h ^= h >>> 16;
  const index = Math.abs(h) % ASN_COLOR_SLOTS;
  return `var(--asn-${index})`;
}
