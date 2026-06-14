// src/hooks/useSiteMetaForm.ts
// Hook for site name, province, and tariff form logic.
// Contract: contracts/frontend/stage_config.md §4.7

import { useState, useEffect, useCallback } from "react";
import { useStageOneStore } from "../stores/stageOneStore";
import type { StageOneStoreState, StageOneStoreActions } from "../stores/stageOneStore";
import type { TariffRegion } from "../types/stageConfig";

// ── Province → default tariff region mapping (static; T-META-2 must work without API) ──
// Maps Chinese province names to the known region_id from tariff_model_schema.
const PROVINCE_TO_TARIFF: Record<string, string> = {
  Gansu:     'cn-gansu',
  Xinjiang:  'cn-xinjiang',
  Qinghai:   'cn-qinghai',
  Ningxia:   'cn-ningxia',
  Shaanxi:   'cn-shaanxi',
  Sichuan:   'cn-sichuan',
  Yunnan:    'cn-yunnan',
  Guizhou:   'cn-guizhou',
  Guangdong: 'cn-guangdong',
  Hunan:     'cn-hunan',
  Hubei:     'cn-hubei',
  Henan:     'cn-henan',
  Shandong:  'cn-shandong',
  // Fallback: province lower-cased prefix lookup is attempted below
};

function getProvinceDefault(province: string): string | undefined {
  if (!province) return undefined;
  if (PROVINCE_TO_TARIFF[province]) return PROVINCE_TO_TARIFF[province];
  // Fallback: "cn-{province-lowercased}" — covers unknown provinces
  return `cn-${province.toLowerCase()}`;
}

export function useSiteMetaForm(_storeArg: StageOneStoreState & StageOneStoreActions) {
  // Subscribe to live store for reactive updates (storeArg is kept for signature compat)
  const liveStore = useStageOneStore();

  const [siteNameError, setSiteNameErrorState] = useState<string | null>(null);
  const [availableTariffs, setAvailableTariffs] = useState<TariffRegion[]>([]);
  const [tariffsLoading, setTariffsLoading] = useState(true);
  const [tariffsError, setTariffsError] = useState<string | null>(null);

  // Fetch tariff list on mount (§5.4)
  useEffect(() => {
    const ctrl = new AbortController();
    setTariffsLoading(true);
    fetch('/api/tariff/regions', { signal: ctrl.signal })
      .then(r => {
        if (!r.ok) throw new Error(`${r.status}`);
        return r.json() as Promise<{ regions: TariffRegion[] }>;
      })
      .then(data => {
        setAvailableTariffs(data.regions ?? []);
        setTariffsLoading(false);
      })
      .catch(err => {
        if ((err as Error).name === 'AbortError') return;
        setTariffsError(String(err));
        setTariffsLoading(false);
      });
    return () => { ctrl.abort(); };
  }, []);

  const setSiteName = useCallback((name: string) => {
    setSiteNameErrorState(name.length > 64 ? `Name must be ≤ 64 characters (${name.length})` : null);
    liveStore.setSiteName(name);
  }, [liveStore]);

  const setProvince = useCallback((province: string) => {
    liveStore.setProvince(province);
    // S1: auto-update tariff to province default if not manually overridden (T-META-2)
    if (!liveStore.tariffManuallyOverridden) {
      const defaultTariff = getProvinceDefault(province);
      if (defaultTariff) {
        liveStore.setTariffRegion(defaultTariff, false);
      }
    }
  }, [liveStore]);

  const setTariffRegion = useCallback((regionId: string, isManual = true) => {
    liveStore.setTariffRegion(regionId, isManual);
  }, [liveStore]);

  const resetTariffToProvinceDefault = useCallback(() => {
    const defaultTariff = getProvinceDefault(liveStore.province);
    if (defaultTariff) {
      liveStore.setTariffRegion(defaultTariff, false);
    }
    liveStore.resetTariffToProvinceDefault();
  }, [liveStore]);

  const showTariffResetLink = liveStore.tariffManuallyOverridden && liveStore.province !== '';

  return {
    siteName:     liveStore.siteName,
    setSiteName,
    siteNameError,

    province:    liveStore.province,
    setProvince,

    tariffRegion:             liveStore.tariffRegion,
    setTariffRegion,
    tariffManuallyOverridden: liveStore.tariffManuallyOverridden,
    resetTariffToProvinceDefault,
    showTariffResetLink,

    availableTariffs,
    tariffsLoading,
    tariffsError,
  };
}
