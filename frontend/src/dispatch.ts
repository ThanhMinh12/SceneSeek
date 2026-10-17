import { Client } from "@gradio/client";

export interface Dispatch { endpoint: string; token: string }
let connection: ReturnType<typeof Client.connect> | undefined;

export async function runDispatch<T>(dispatch: Dispatch): Promise<T> {
  try {
    connection ??= Client.connect(window.location.origin, { status_callback: () => undefined });
    const client = await connection;
    const result = await client.predict(dispatch.endpoint, { token: dispatch.token });
    if (!Array.isArray(result.data) || result.data.length === 0) throw new Error("The inference server returned an invalid response.");
    return result.data[0] as T;
  } catch (error) {
    connection = undefined;
    await fetch("/api/dispatch/cancel", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token: dispatch.token }),
    }).catch(() => undefined);
    throw error;
  }
}

