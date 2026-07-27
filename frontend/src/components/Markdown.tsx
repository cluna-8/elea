import React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

// Renderer compartido para respuestas del asistente (portal de usuario final).
// El motor devuelve markdown (títulos, negritas, listas); sin esto el texto
// muestra la sintaxis cruda ("**", "#") en lugar de formatearla.
// Portado del predecesor y reescrito sobre los tokens del tema claro (029):
// nada de clases oscuras (text-white / bg-black) ni hex hardcodeado.
export const Markdown: React.FC<{ children: string; className?: string }> = ({ children, className }) => (
  <div className={`text-sm leading-relaxed space-y-2 ${className ?? ""}`}>
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        p: ({ children }) => <p className="whitespace-pre-wrap">{children}</p>,
        strong: ({ children }) => <strong className="font-semibold text-text-primary">{children}</strong>,
        em: ({ children }) => <em className="italic">{children}</em>,
        ul: ({ children }) => <ul className="list-disc list-inside space-y-0.5 ml-1">{children}</ul>,
        ol: ({ children }) => <ol className="list-decimal list-inside space-y-0.5 ml-1">{children}</ol>,
        li: ({ children }) => <li>{children}</li>,
        h1: ({ children }) => <h1 className="text-base font-semibold text-text-primary mt-2">{children}</h1>,
        h2: ({ children }) => <h2 className="text-sm font-semibold text-text-primary mt-2">{children}</h2>,
        h3: ({ children }) => <h3 className="text-sm font-semibold text-text-primary mt-1">{children}</h3>,
        code: ({ children }) => (
          <code className="bg-surface-2 border border-border rounded px-1 py-0.5 text-[11px] font-mono">{children}</code>
        ),
        pre: ({ children }) => (
          <pre className="bg-surface-2 border border-border rounded p-2 overflow-x-auto text-[11px] font-mono">{children}</pre>
        ),
        a: ({ children, href }) => (
          <a href={href} target="_blank" rel="noopener noreferrer" className="text-primary underline">
            {children}
          </a>
        ),
        blockquote: ({ children }) => (
          <blockquote className="border-l-2 border-border pl-3 text-text-secondary">{children}</blockquote>
        ),
        hr: () => <hr className="border-border my-2" />,
      }}
    >
      {children}
    </ReactMarkdown>
  </div>
);
