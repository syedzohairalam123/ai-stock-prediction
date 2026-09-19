/**
 * useVoiceInput — browser speech-to-text with honest states (spec M)
 *
 * States: idle → listening → processing → idle, or `unsupported` when the
 * browser has no SpeechRecognition implementation. Nothing here throws: an
 * unsupported browser, a denied microphone and a dropped recognition session
 * all resolve to a message the composer can display.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useAIStore, VoiceStatus } from '../store/useAIStore';

// ---- minimal Web Speech API surface (not in lib.dom for all TS versions) ----

interface SpeechRecognitionAlternative {
  transcript: string;
  confidence: number;
}

interface SpeechRecognitionResult {
  readonly length: number;
  isFinal: boolean;
  item(index: number): SpeechRecognitionAlternative;
  [index: number]: SpeechRecognitionAlternative;
}

interface SpeechRecognitionResultList {
  readonly length: number;
  item(index: number): SpeechRecognitionResult;
  [index: number]: SpeechRecognitionResult;
}

interface SpeechRecognitionEventLike extends Event {
  resultIndex: number;
  results: SpeechRecognitionResultList;
}

interface SpeechRecognitionErrorEventLike extends Event {
  error: string;
  message?: string;
}

interface SpeechRecognitionLike extends EventTarget {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  start(): void;
  stop(): void;
  abort(): void;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  onerror: ((event: SpeechRecognitionErrorEventLike) => void) | null;
  onend: (() => void) | null;
  onstart: (() => void) | null;
}

type SpeechRecognitionCtor = new () => SpeechRecognitionLike;

function getRecognitionCtor(): SpeechRecognitionCtor | null {
  if (typeof window === 'undefined') return null;
  const candidate =
    (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
  return typeof candidate === 'function' ? (candidate as SpeechRecognitionCtor) : null;
}

const ERROR_MESSAGES: Record<string, string> = {
  'not-allowed': 'Microphone access was blocked. Allow it in your browser settings, then try again.',
  'service-not-allowed': 'The browser blocked speech recognition on this page.',
  'no-speech': 'No speech detected. Tap the microphone and try again.',
  'audio-capture': 'No microphone was found on this device.',
  network: 'Speech recognition needs a network connection.',
  aborted: '',
};

export interface UseVoiceInputResult {
  supported: boolean;
  status: VoiceStatus;
  error: string | null;
  start: () => void;
  stop: () => void;
  toggle: () => void;
}

export interface UseVoiceInputOptions {
  /** Receives recognized text. `isFinal` marks a completed phrase. */
  onTranscript: (text: string, isFinal: boolean) => void;
  lang?: string;
}

export function useVoiceInput({ onTranscript, lang = 'en-US' }: UseVoiceInputOptions): UseVoiceInputResult {
  const supported = useMemo(() => getRecognitionCtor() !== null, []);
  const [error, setError] = useState<string | null>(null);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const manuallyStoppedRef = useRef(false);
  const transcriptHandlerRef = useRef(onTranscript);
  transcriptHandlerRef.current = onTranscript;

  const status = useAIStore((state) => state.voiceStatus);
  const setVoiceStatus = useAIStore((state) => state.setVoiceStatus);
  const setVoiceError = useAIStore((state) => state.setVoiceError);

  // Report the unsupported capability once, without breaking the composer.
  useEffect(() => {
    if (!supported) {
      setVoiceStatus('unsupported');
      setVoiceError('Voice input is unavailable in this browser.');
    }
  }, [supported, setVoiceError, setVoiceStatus]);

  // Tear the microphone down if the user navigates away mid-sentence.
  useEffect(() => {
    return () => {
      try {
        recognitionRef.current?.abort();
      } catch {
        /* already stopped */
      }
      recognitionRef.current = null;
    };
  }, []);

  const stop = useCallback(() => {
    manuallyStoppedRef.current = true;
    try {
      recognitionRef.current?.stop();
    } catch {
      /* nothing to stop */
    }
    setVoiceStatus('idle');
  }, [setVoiceStatus]);

  const start = useCallback(() => {
    const Ctor = getRecognitionCtor();
    if (!Ctor) {
      setVoiceStatus('unsupported');
      setVoiceError('Voice input is unavailable in this browser.');
      return;
    }

    // Reuse a live session rather than spawning a second microphone stream.
    if (recognitionRef.current) {
      stop();
      return;
    }

    setVoiceError(null);
    setError(null);
    manuallyStoppedRef.current = false;

    const recognition = new Ctor();
    recognition.lang = lang;
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.maxAlternatives = 1;

    recognition.onstart = () => setVoiceStatus('listening');

    recognition.onresult = (event) => {
      let interim = '';
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const result = event.results[i];
        const text = result[0]?.transcript ?? '';
        if (result.isFinal) {
          transcriptHandlerRef.current(text.trim(), true);
        } else {
          interim += text;
        }
      }
      if (interim) transcriptHandlerRef.current(interim.trim(), false);
    };

    recognition.onerror = (event) => {
      const message = ERROR_MESSAGES[event.error] ?? 'Voice input failed. Please try again.';
      if (message) setError(message);
      setVoiceError(message || null);
      setVoiceStatus('idle');
      recognitionRef.current = null;
    };

    recognition.onend = () => {
      recognitionRef.current = null;
      if (manuallyStoppedRef.current) {
        setVoiceStatus('idle');
        return;
      }
      // Natural end of a phrase: briefly show "processing" so the user sees
      // their words land in the composer rather than the mic blinking off.
      setVoiceStatus('processing');
      window.setTimeout(() => setVoiceStatus('idle'), 400);
    };

    recognitionRef.current = recognition;

    try {
      recognition.start();
      setVoiceStatus('listening');
    } catch {
      recognitionRef.current = null;
      setVoiceStatus('idle');
      setVoiceError('Could not start the microphone. It may already be in use.');
    }
  }, [lang, setVoiceError, setVoiceStatus, stop]);

  const toggle = useCallback(() => {
    if (status === 'listening') stop();
    else start();
  }, [start, status, stop]);

  return { supported, status, error: error ?? null, start, stop, toggle };
}
