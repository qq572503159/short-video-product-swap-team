import { createHash } from "node:crypto";

import {
  canonicalize,
  defineEndpointPackage,
  wakeAfter,
} from "@hypit/hypit/endpoint-kit";
import type {
  AsyncEndpoint,
  CredentialRef,
  EndpointRequest,
} from "@hypit/hypit/endpoint-kit";
import {
  compileWireRequest,
  generationTypes,
  sealGeneratedVideoSet,
  selectWireModelForRequest,
} from "@hypit/hypit/generation";
import type {
  GenerationRequest,
  GenerationWireMapping,
} from "@hypit/hypit/generation";

export const providerModule = { name: "@local/provider-newapi-video", version: "1" } as const;
export const capability = {
  module: { name: "@hypit/seedance", version: "1" },
  name: "seedance-2-mini",
} as const;

const mapping: GenerationWireMapping = {
  capability,
  result: "video",
  routes: [{ model: "seedance-2.0-mini" }],
  fields: {
    prompt: { as: "value", field: "prompt" },
    referenceImage: { as: "urlArray", field: "referenceImages" },
    referenceVideo: { as: "urlArray", field: "referenceVideos" },
    referenceAudio: { as: "urlArray", field: "referenceAudios" },
    firstFrame: { as: "url", field: "firstFrame" },
    lastFrame: { as: "url", field: "lastFrame" },
    resolution: { as: "value", field: "resolution" },
    aspectRatio: { as: "value", field: "ratio" },
    duration: { as: "value", field: "duration" },
    generateAudio: { as: "value", field: "generateAudio" },
    webSearch: { as: "value", field: "webSearch" },
  },
};

function object(value: unknown, subject = "service response"): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${subject} must be an object`);
  }
  return value as Record<string, unknown>;
}

function text(value: unknown, subject = "service text"): string {
  if (typeof value !== "string" || value.trim().length === 0) {
    throw new Error(`${subject} must be non-empty text`);
  }
  return value.trim();
}

function publicMessage(value: unknown): string | undefined {
  if (typeof value !== "string" || value.trim().length === 0) return undefined;
  return value.replace(/https?:\/\/\S+/giu, "[redacted-url]").slice(0, 500);
}

function serviceUrl(value: string): string {
  const url = new URL(value);
  if (url.protocol !== "https:" && !(url.protocol === "http:" && ["localhost", "127.0.0.1"].includes(url.hostname))) {
    throw new Error("New API URLs require HTTPS or loopback HTTP");
  }
  return url.href;
}

function apiRoot(value: string): string {
  const base = serviceUrl(value).replace(/\/$/u, "");
  return base.endsWith("/v1") ? base : `${base}/v1`;
}

function resultUrl(response: Record<string, unknown>): string | undefined {
  const direct = response.video_url ?? response.url;
  if (typeof direct === "string" && direct.length > 0) return serviceUrl(direct);
  const data = response.data;
  if (data !== null && typeof data === "object" && !Array.isArray(data)) {
    const nested = (data as Record<string, unknown>).video_url ?? (data as Record<string, unknown>).url;
    if (typeof nested === "string" && nested.length > 0) return serviceUrl(nested);
  }
  return undefined;
}

function support(request: EndpointRequest) {
  const authored = request.constraints as unknown as GenerationRequest;
  if (authored.ports.webSearch?.[0] === true) {
    return { status: "unsupported" as const, reason: "New API Seedance mini does not expose web search" };
  }
  if (authored.ports.generateAudio?.[0] === true) {
    return { status: "unsupported" as const, reason: "This workflow generates silent video and restores the original audio locally" };
  }
  const known = new Set(Object.keys(mapping.fields));
  const unknown = Object.keys(authored.ports).filter((name) => !known.has(name));
  const pendingUnknown = request.pendingInputs?.filter((slot) => !known.has(slot.input)) ?? [];
  return unknown.length > 0 || pendingUnknown.length > 0
    ? { status: "unsupported" as const, reason: `New API adapter does not map ports: ${[...unknown, ...pendingUnknown.map((slot) => slot.input)].join(", ")}` }
    : { status: "supported" as const };
}

export function createNewApiVideoProvider(options: {
  instance: string;
  pool: string;
  baseUrl: string;
  apiKey: CredentialRef;
  assetUrls: Readonly<Record<string, string>>;
  defaultConcurrency?: number;
  pollIntervalMs?: number;
  fetch?: typeof globalThis.fetch;
}) {
  const base = apiRoot(options.baseUrl);
  const fetcher = options.fetch ?? globalThis.fetch;
  const interval = options.pollIntervalMs ?? 3_000;
  const credential = (credentials: Readonly<Record<string, { secret: string }>>) =>
    text(credentials.apiKey?.secret, "New API credential");

  async function json(path: string, secret: string, init: RequestInit = {}) {
    const response = await fetcher(`${base}${path}`, {
      ...init,
      headers: {
        accept: "application/json",
        authorization: `Bearer ${secret}`,
        ...init.headers,
      },
      signal: AbortSignal.timeout(60_000),
    });
    if (!response.ok) {
      let detail: string | undefined;
      try {
        const body = object(await response.json());
        const error = body.error;
        detail = typeof error === "string"
          ? publicMessage(error)
          : error === null || typeof error !== "object" || Array.isArray(error)
            ? publicMessage(body.message)
            : publicMessage((error as Record<string, unknown>).message);
      } catch {
        // HTTP status remains sufficient public failure evidence.
      }
      throw new Error(`New API ${init.method ?? "GET"} ${path} returned HTTP ${response.status}${detail === undefined ? "" : `: ${detail}`}`);
    }
    return object(await response.json());
  }

  const endpoint: AsyncEndpoint = {
    async start(context) {
      const supported = support(context.need);
      if (supported.status === "unsupported") throw new Error(supported.reason);
      const secret = credential(context.credentials);
      const authored = context.need.constraints as unknown as GenerationRequest;
      const model = selectWireModelForRequest(mapping, authored);
      await context.reportProgress?.({ phase: `Preparing New API video request: ${model}` });
      const compiled = await compileWireRequest(mapping, authored, async (artifact) => {
        const bytes = await context.resources.get(artifact.resource);
        if (bytes === undefined) throw new Error("New API reference asset is unavailable");
        const hash = createHash("sha256").update(bytes).digest("hex");
        const url = options.assetUrls[hash];
        if (url === undefined) {
          throw new Error(`New API reference asset ${hash} has no configured public URL`);
        }
        return serviceUrl(url);
      });
      const input = { ...(compiled.input as Record<string, unknown>) };
      if (input.generateAudio === false) delete input.generateAudio;
      if (input.webSearch === false) delete input.webSearch;
      await context.reportProgress?.({ phase: `Submitting New API video request: ${model}` });
      const created = await json("/videos", secret, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ model: compiled.model, ...input }),
      });
      const id = text(created.task_id ?? created.id, "New API task id");
      const handle = { id };
      await context.checkpoint?.({ handle, receipt: { id } });
      return { ...wakeAfter(handle, interval), receipt: { id } };
    },
    async poll(context) {
      const id = text(object(context.handle, "New API handle").id, "New API task id");
      const response = await json(`/videos/${encodeURIComponent(id)}`, credential(context.credentials));
      const state = String(response.status ?? "").toLowerCase();
      if (["queued", "pending", "running", "processing", "in_progress", "submitted"].includes(state)) {
        return wakeAfter({ id }, interval, Date.now(), { phase: state || "processing" });
      }
      if (["failed", "error", "cancelled", "canceled"].includes(state)) {
        const message = publicMessage(response.message)
          ?? publicMessage(response.error)
          ?? `New API task ${id} failed with status ${state}`;
        return { status: "failed", receipt: { id }, failure: { code: "NEW_API_VIDEO_FAILED", message } };
      }
      if (!["completed", "succeeded", "success"].includes(state)) {
        throw new Error(`New API task ${id} returned unknown status: ${state || "missing"}`);
      }
      const url = resultUrl(response);
      if (url === undefined) throw new Error(`New API task ${id} completed without a video URL`);
      return { status: "ready", handle: { id, url } };
    },
    async collect(context) {
      const handle = object(context.handle, "New API collection handle");
      const url = serviceUrl(text(handle.url, "New API result URL"));
      await context.reportProgress?.({ phase: "Receiving generated New API video" });
      const response = await fetcher(url, { signal: AbortSignal.timeout(120_000) });
      if (!response.ok) throw new Error(`New API video download returned HTTP ${response.status}`);
      const headerType = response.headers.get("content-type")?.split(";")[0]?.trim();
      const mediaType = headerType?.startsWith("video/") ? headerType : "video/mp4";
      const artifact = await context.resources.put(new Uint8Array(await response.arrayBuffer()), mediaType);
      return {
        status: "completed",
        result: {
          value: {
            kind: "inline",
            value: canonicalize(sealGeneratedVideoSet({ videos: [artifact] })),
          },
        },
      };
    },
  };

  return defineEndpointPackage({
    module: providerModule,
    facet: "videos",
    instance: options.instance,
    pool: options.pool,
    credentials: { apiKey: options.apiKey },
    credentialInputs: { apiKey: { label: "New API key" } },
    defaultConcurrency: options.defaultConcurrency ?? 1,
    actionLimits: {
      submit: { concurrency: 1 },
      poll: { concurrency: 4 },
      collect: { concurrency: 1 },
    },
    pricing: { kind: "page", url: `${new URL(base).origin}/video-docs` },
    capabilities: [{
      capability,
      returns: generationTypes.videoSet,
      lifecycle: "asynchronous",
      supports: support,
      endpoint,
    }],
  });
}
