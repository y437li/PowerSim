/**
 * inferenceSessionStore — inference session state and session control actions.
 * Contract: contracts/frontend/inference_session.md §3
 *
 * Stub — implementation pending contract approval.
 */
export const inferenceSessionStore = {
  getState: () => ({
    serverState: "idle" as const,
    runId: null as string | null,
    siteId: null as string | null,
    sessionId: null as string | null,
    step: 0,
    episode: 0,
    speed: 1.0,
    errorMsg: null as string | null,
    handleServerStatus: (_frame: unknown) => {},
    handleServerError: (_frame: unknown) => {},
    pause: () => {},
    resume: () => {},
    setSpeed: (_speed: number) => {},
  }),
  subscribe: (_fn: unknown) => () => {},
};

export const useInferenceSessionStore = <T>(sel: (s: ReturnType<typeof inferenceSessionStore.getState>) => T): T =>
  sel(inferenceSessionStore.getState());
