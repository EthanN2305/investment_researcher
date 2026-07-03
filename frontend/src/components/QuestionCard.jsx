import { useState } from "react";

// Renders the planner's clarifying question. Option buttons answer with one
// click; the free-text field covers "Other" style answers.
export default function QuestionCard({ question, options = [], onAnswer, busy }) {
  const [text, setText] = useState("");

  return (
    <div className="question-card" role="alertdialog" aria-label="Clarifying question">
      <p className="question-text">
        <span className="question-icon" aria-hidden="true">?</span>
        {question}
      </p>
      {options.length > 0 && (
        <div className="question-options">
          {options.map((opt) => (
            <button
              key={opt}
              type="button"
              disabled={busy}
              onClick={() => onAnswer(opt)}
            >
              {opt}
            </button>
          ))}
        </div>
      )}
      <form
        className="question-freeform"
        onSubmit={(e) => {
          e.preventDefault();
          if (text.trim()) onAnswer(text.trim());
        }}
      >
        <input
          placeholder="Or type an answer…"
          value={text}
          disabled={busy}
          onChange={(e) => setText(e.target.value)}
        />
        <button type="submit" disabled={busy || !text.trim()}>
          Answer
        </button>
      </form>
    </div>
  );
}
