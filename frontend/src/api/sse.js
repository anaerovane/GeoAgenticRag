/**
 * Robust SSE frame parser for the jevrag stream.
 *
 * The server emits canonical frames:
 *   event: <name>\n
 *   data: {"event": <name>, "data": {...}}\n
 *   \n
 * but chunks may split frames anywhere, flush several frames at once, or
 * carry multi-line `data:` fields. We buffer on \n\n and parse per spec.
 */

/** Parse one raw frame (text between blank lines) into {event, data}. */
export function parseFrame(raw) {
  let event = null;
  const dataLines = [];
  for (const line of raw.split('\n')) {
    if (!line || line.startsWith(':')) continue; // comment / keep-alive
    const colon = line.indexOf(':');
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? '' : line.slice(colon + 1);
    if (value.startsWith(' ')) value = value.slice(1);
    if (field === 'event') event = value.trim();
    else if (field === 'data') dataLines.push(value);
  }
  if (dataLines.length === 0) return null;
  const text = dataLines.join('\n');
  let payload;
  try {
    payload = JSON.parse(text);
  } catch {
    return { event: event || 'message', data: { raw: text } };
  }
  // Server wraps frames as {"event": name, "data": {...}}; fall back to it
  // when the `event:` line is missing.
  const name = event || payload?.event || 'message';
  const data = payload && typeof payload === 'object' && 'data' in payload
    ? payload.data
    : payload;
  return { event: name, data };
}

/**
 * Consume a fetch Response body and yield parsed {event, data} frames.
 * Handles partial UTF-8 chunks, multi-frame chunks and trailing partials.
 */
export async function* readSse(response) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let split;
      while ((split = buffer.indexOf('\n\n')) !== -1) {
        const raw = buffer.slice(0, split);
        buffer = buffer.slice(split + 2);
        const frame = parseFrame(raw);
        if (frame) yield frame;
      }
    }
    buffer += decoder.decode();
  } finally {
    reader.releaseLock();
  }
  // Flush any trailing frame that was not terminated by a blank line.
  const tail = buffer.trim();
  if (tail) {
    const frame = parseFrame(tail);
    if (frame) yield frame;
  }
}
