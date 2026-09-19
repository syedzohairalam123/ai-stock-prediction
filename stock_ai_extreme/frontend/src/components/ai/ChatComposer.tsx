/**
 * ChatComposer — the question box (spec B / L / M / U / Z).
 *
 * Auto-growing input, Enter to send (Shift+Enter for a new line), a send button
 * that becomes "Stop generating" mid-answer, and a real microphone wired to the
 * browser's speech recognition. When voice is unsupported the button says so
 * instead of failing silently.
 */

import { FormEvent, KeyboardEvent, useEffect, useRef, useState } from 'react';
import { AlertTriangle, Mic, MicOff, Send, Square } from 'lucide-react';
import { AIContext } from '../../lib/aiService';
import { UseChatResult } from '../../hooks/useChat';
import { useVoiceInput } from '../../hooks/useVoiceInput';
import { useAIStore } from '../../store/useAIStore';
import { SuggestedPrompts } from './SuggestedPrompts';

interface ChatComposerProps {
  context: AIContext;
  chat: UseChatResult;
}

const MAX_QUESTION_LENGTH = 2000;
const WARN_AT = MAX_QUESTION_LENGTH - 200;

export function ChatComposer({ context, chat }: ChatComposerProps) {
  const [input, setInput] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const voiceBaseRef = useRef('');
  const voiceFinalRef = useRef('');

  const aiStatus = useAIStore((state) => state.aiStatus);
  const voiceStatus = useAIStore((state) => state.voiceStatus);
  const voiceError = useAIStore((state) => state.voiceError);

  const { isStreaming, messages, status, send, stop } = chat;
  const showPromptRail = messages.length > 0 && !isStreaming && status === 'idle';

  const voice = useVoiceInput({
    lang: 'en-US',
    onTranscript: (text, isFinal) => {
      if (!text) return;
      // Final phrases accumulate; interim phrases preview on top of them.
      if (isFinal) voiceFinalRef.current = `${voiceFinalRef.current} ${text}`.trim();
      const spoken = isFinal ? voiceFinalRef.current : `${voiceFinalRef.current} ${text}`.trim();
      setInput(`${voiceBaseRef.current} ${spoken}`.replace(/\s+/g, ' ').trim());
    },
  });

  // Keep the caret visible as the box grows.
  useEffect(() => {
    const node = textareaRef.current;
    if (!node) return;
    node.style.height = 'auto';
    node.style.height = `${Math.min(node.scrollHeight, 168)}px`;
  }, [input]);

  const submit = (event?: FormEvent) => {
    event?.preventDefault();
    const question = input.trim();
    if (!question || isStreaming) return;
    if (voiceStatus === 'listening') voice.stop();
    send(question);
    setInput('');
    voiceBaseRef.current = '';
    voiceFinalRef.current = '';
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  };

  const handleMic = () => {
    if (!voice.supported) return;
    if (voiceStatus === 'idle' || voiceStatus === 'processing') {
      voiceBaseRef.current = input;
      voiceFinalRef.current = '';
    }
    voice.toggle();
  };

  const handlePrompt = (prompt: string) => {
    setInput('');
    voiceBaseRef.current = '';
    voiceFinalRef.current = '';
    send(prompt);
  };

  const overLimit = input.length > MAX_QUESTION_LENGTH;
  const unavailable = aiStatus?.available === false;
  const unreachable = aiStatus?.unreachable === true;
  const micTitle = !voice.supported
    ? 'Voice input is unavailable in this browser.'
    : voiceStatus === 'listening'
      ? 'Stop listening'
      : voiceStatus === 'processing'
        ? 'Processing your words…'
        : 'Ask by voice';

  return (
    <div className="ai-composer">
      {unreachable && (
        <div className="ai-notice" role="status">
          <AlertTriangle aria-hidden />
          <span>
            <b>The assistant backend is unreachable.</b> The API is not answering — start it, check
            the URL, then reopen this panel. The rest of the terminal keeps working normally.
          </span>
        </div>
      )}

      {unavailable && !unreachable && (
        <div className="ai-notice" role="status">
          <AlertTriangle aria-hidden />
          <span>
            <b>The assistant is not configured on this server.</b> Set <code>AI_PROVIDER</code> and
            the matching key (<code>OPENAI_API_KEY</code>, <code>OPENROUTER_API_KEY</code> or{' '}
            <code>ANTHROPIC_API_KEY</code>) in the backend environment, then restart the API. The
            rest of the terminal keeps working normally.
          </span>
        </div>
      )}

      {showPromptRail && (
        <SuggestedPrompts context={context} onSelect={handlePrompt} variant="rail" />
      )}

      <form onSubmit={submit} className="ai-composer-row">
        <div className="ai-field">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={handleKeyDown}
            rows={1}
            placeholder={`Ask about ${context.symbol ?? 'the market'}, news, sentiment or your portfolio…`}
            aria-label="Ask the market assistant"
            aria-describedby="ai-composer-hint"
          />

          <div className="ai-field-foot">
            <span className="ai-hint" id="ai-composer-hint">
              <kbd>Enter</kbd> to send · <kbd>Shift</kbd>+<kbd>Enter</kbd> for a new line
            </span>
            <span className={`ai-counter${input.length > WARN_AT ? ' warn' : ''}`}>
              {input.length}/{MAX_QUESTION_LENGTH}
            </span>
          </div>
        </div>

        {isStreaming ? (
          <button
            type="button"
            className="ai-round stop"
            onClick={stop}
            title="Stop generating"
            aria-label="Stop generating"
          >
            <Square aria-hidden />
          </button>
        ) : (
          <button
            type="submit"
            className="ai-round send"
            disabled={!input.trim() || overLimit}
            title="Send question"
            aria-label="Send question"
          >
            <Send aria-hidden />
          </button>
        )}

        <button
          type="button"
          className={`ai-round ${voiceStatus === 'listening' ? 'listening' : 'ghost'}`}
          onClick={handleMic}
          disabled={!voice.supported}
          title={micTitle}
          aria-label={micTitle}
          aria-pressed={voiceStatus === 'listening'}
        >
          {voice.supported ? <Mic aria-hidden /> : <MicOff aria-hidden />}
        </button>
      </form>

      {voiceStatus === 'listening' && (
        <div className="ai-voice-note" role="status">
          Listening… speak your question, it appears in the box above.
        </div>
      )}
      {voiceStatus !== 'listening' && voiceError && (
        <div className="ai-voice-note" role="status">
          {voiceError}
        </div>
      )}

      <p className="ai-disclaimer">
        Educational analytics only — not investment advice. Every answer shows the data it used.
      </p>

      <span className="ai-sr" aria-live="polite">
        {isStreaming ? 'Assistant is answering' : ''}
      </span>
    </div>
  );
}

export default ChatComposer;
