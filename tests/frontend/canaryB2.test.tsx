// CANARY B2 — gate-safety canary (criterion B). Deliberate failing frontend test
// to prove `checks` BLOCKS when frontend-tests fails. THROWAWAY — never merged.
import { describe, it, expect } from 'vitest';
describe('canary B2', () => {
  it('deliberate frontend-tests failure', () => { expect(true).toBe(false); });
});
