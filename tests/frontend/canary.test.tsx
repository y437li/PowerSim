// CANARY B2 — gate-safety (criterion B). Deliberate frontend-tests failure; throwaway.
import { describe, it, expect } from 'vitest';
describe('canary B2', () => { it('deliberate failure', () => { expect(true).toBe(false); }); });
