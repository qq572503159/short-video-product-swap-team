import {
  createRuntimeEndpointAdapterFacet,
  runtimeConfigCredentialRef,
  runtimeConfigExact,
  runtimeConfigObject,
  runtimeConfigPositiveInteger,
  runtimeConfigString,
} from "@hypit/hypit/runtime-kit";

import { createNewApiVideoProvider, providerModule } from "./provider.js";

function assetUrlMap(
  value: Parameters<typeof runtimeConfigObject>[0] | undefined,
): Readonly<Record<string, string>> {
  if (value === undefined) return {};
  const object = runtimeConfigObject(value, "New API assetUrls");
  return Object.fromEntries(Object.entries(object).map(([hash, rawUrl]) => {
    const normalizedHash = hash.toLowerCase();
    if (!/^[a-f0-9]{64}$/u.test(normalizedHash)) {
      throw new Error(`New API assetUrls key must be a SHA-256 hash: ${hash}`);
    }
    const url = runtimeConfigString(rawUrl, `New API assetUrls.${hash}`);
    if (url === undefined) throw new Error(`New API assetUrls.${hash} must be a URL`);
    return [normalizedHash, url];
  }));
}

export default {
  format: "hypit.node-package@1" as const,
  hostFacets: [createRuntimeEndpointAdapterFacet({
    use: providerModule.name,
    activate(context) {
      if (context.pool === undefined) throw new Error("New API Provider Pool is required");
      const config = runtimeConfigObject(context.config, "New API video service");
      runtimeConfigExact(config, [
        "baseUrl",
        "apiKey",
        "defaultConcurrency",
        "pollIntervalMs",
        "assetUrls",
      ], "New API video service");
      const baseUrl = runtimeConfigString(config.baseUrl, "New API baseUrl");
      const apiKey = runtimeConfigCredentialRef(config.apiKey, "New API apiKey");
      if (baseUrl === undefined || apiKey === undefined) {
        throw new Error("New API video service requires baseUrl and apiKey");
      }
      return {
        endpoint: createNewApiVideoProvider({
          instance: context.instance,
          pool: context.pool,
          baseUrl,
          apiKey,
          assetUrls: assetUrlMap(config.assetUrls),
          defaultConcurrency: runtimeConfigPositiveInteger(
            config.defaultConcurrency,
            "New API defaultConcurrency",
          ) ?? 1,
          pollIntervalMs: runtimeConfigPositiveInteger(
            config.pollIntervalMs,
            "New API pollIntervalMs",
          ) ?? 3_000,
        }),
      };
    },
  })],
};
