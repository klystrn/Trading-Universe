/** Browser speech: push-to-talk recognition and spoken replies.
 *
 *  Uses the Web Speech API only - no service, no key. Recognition exists in
 *  Chrome and Edge; elsewhere the mic button reports itself unavailable and
 *  the command line still works. Synthesis is everywhere.
 */

type RecognitionCtor = new () => SpeechRecognitionLike;
interface SpeechRecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((e: { resultIndex: number; results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal: boolean }> }) => void) | null;
  onend: (() => void) | null;
  onerror: ((e: { error: string }) => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}

export function recognitionSupported(): boolean {
  if (typeof window === "undefined") return false;
  const w = window as unknown as { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor };
  return !!(w.SpeechRecognition ?? w.webkitSpeechRecognition);
}

export function createRecognizer(handlers: {
  onInterim: (text: string) => void;
  onFinal: (text: string) => void;
  onEnd: () => void;
  onError: (message: string) => void;
}): SpeechRecognitionLike | null {
  if (!recognitionSupported()) return null;
  const w = window as unknown as { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor };
  const Ctor = (w.SpeechRecognition ?? w.webkitSpeechRecognition)!;
  const rec = new Ctor();
  rec.lang = "en-US";
  rec.continuous = false;
  rec.interimResults = true;
  rec.onresult = (e) => {
    let interim = "";
    let final = "";
    for (let i = e.resultIndex; i < e.results.length; i += 1) {
      const result = e.results[i];
      const text = result[0].transcript;
      if (result.isFinal) final += text;
      else interim += text;
    }
    if (final) handlers.onFinal(final.trim());
    else if (interim) handlers.onInterim(interim.trim());
  };
  rec.onend = handlers.onEnd;
  rec.onerror = (e) => handlers.onError(e.error);
  return rec;
}

let preferredVoice: SpeechSynthesisVoice | null | undefined;

function pickVoice(): SpeechSynthesisVoice | null {
  if (preferredVoice !== undefined) return preferredVoice;
  const voices = window.speechSynthesis.getVoices();
  // A calm, low, British-leaning voice suits the role; fall back sensibly.
  const wanted = ["Daniel", "Google UK English Male", "Microsoft Ryan", "Microsoft George", "Alex"];
  preferredVoice =
    voices.find((v) => wanted.some((w) => v.name.includes(w))) ??
    voices.find((v) => v.lang === "en-GB") ??
    voices.find((v) => v.lang.startsWith("en")) ??
    null;
  return preferredVoice;
}

export function speak(text: string, onStart?: () => void, onEnd?: () => void): void {
  if (typeof window === "undefined" || !("speechSynthesis" in window) || !text) {
    onEnd?.();
    return;
  }
  const synth = window.speechSynthesis;
  synth.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  const voice = pickVoice();
  if (voice) utterance.voice = voice;
  utterance.rate = 1.02;
  utterance.pitch = 0.88;
  utterance.onstart = () => onStart?.();
  utterance.onend = () => onEnd?.();
  utterance.onerror = () => onEnd?.();
  synth.speak(utterance);
}

export function stopSpeaking(): void {
  if (typeof window !== "undefined" && "speechSynthesis" in window) window.speechSynthesis.cancel();
}

// Voices load asynchronously in Chrome; warm the cache.
if (typeof window !== "undefined" && "speechSynthesis" in window) {
  window.speechSynthesis.onvoiceschanged = () => { preferredVoice = undefined; };
}
