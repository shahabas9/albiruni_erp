import { useCallback, useEffect, useRef, useState } from "react";

// The Web Speech API isn't in lib.dom's typings yet; this is the slice we use.
interface RecognitionResultEvent {
  results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal: boolean }>;
}
interface Recognition {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  start(): void;
  stop(): void;
  abort(): void;
  onresult: ((e: RecognitionResultEvent) => void) | null;
  onerror: ((e: { error: string }) => void) | null;
  onend: (() => void) | null;
}
type RecognitionCtor = new () => Recognition;

function getCtor(): RecognitionCtor | null {
  const w = window as unknown as { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

/**
 * Browser speech-to-text. `supported` is false on Firefox and some Safari
 * builds — callers should disable the mic rather than hide typing.
 * `onFinal` receives the full transcript once the speaker stops.
 */
export function useSpeech(lang: string, onFinal: (text: string) => void) {
  const [listening, setListening] = useState(false);
  const [interim, setInterim] = useState("");
  const [error, setError] = useState<string | null>(null);
  const recRef = useRef<Recognition | null>(null);
  const onFinalRef = useRef(onFinal);
  useEffect(() => {
    onFinalRef.current = onFinal;
  }, [onFinal]);
  const supported = typeof window !== "undefined" && getCtor() !== null;

  useEffect(() => () => recRef.current?.abort(), []);

  const start = useCallback(() => {
    const Ctor = getCtor();
    if (!Ctor || recRef.current) return;
    const rec = new Ctor();
    rec.lang = lang;
    rec.interimResults = true;
    rec.continuous = false;
    let finalText = "";
    rec.onresult = (e) => {
      let live = "";
      finalText = "";
      for (let i = 0; i < e.results.length; i++) {
        const r = e.results[i]!;
        if (r.isFinal) finalText += r[0]!.transcript;
        else live += r[0]!.transcript;
      }
      setInterim(finalText + live);
    };
    rec.onerror = (e) => {
      setError(e.error === "not-allowed" ? "Microphone access was blocked." : `Voice input failed (${e.error}).`);
    };
    rec.onend = () => {
      recRef.current = null;
      setListening(false);
      setInterim("");
      const text = finalText.trim();
      if (text) onFinalRef.current(text);
    };
    setError(null);
    recRef.current = rec;
    setListening(true);
    rec.start();
  }, [lang]);

  const stop = useCallback(() => recRef.current?.stop(), []);
  const toggle = useCallback(() => (recRef.current ? stop() : start()), [start, stop]);

  return { supported, listening, interim, error, start, stop, toggle };
}
