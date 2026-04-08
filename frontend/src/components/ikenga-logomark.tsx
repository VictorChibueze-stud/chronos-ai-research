import type { CSSProperties } from "react";

/** Concentric-rings + crosshair mark (matches sidebar branding). */
export function IkengaLogomark({
  size = 20,
  className,
  style,
  "aria-hidden": ariaHidden = true,
}: {
  size?: number;
  className?: string;
  style?: CSSProperties;
  "aria-hidden"?: boolean;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 20 20"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      style={style}
      aria-hidden={ariaHidden}
    >
      <circle cx="10" cy="10" r="8" fill="none" stroke="#F5A623" strokeWidth="0.8" opacity="0.4" />
      <circle cx="10" cy="10" r="5" fill="none" stroke="#F5A623" strokeWidth="0.8" opacity="0.7" />
      <path
        d="M10 3 L10 6 M8.5 5 L10 6.5 L11.5 5"
        fill="none"
        stroke="#F5A623"
        strokeWidth="0.8"
        strokeLinecap="round"
        strokeLinejoin="round"
        opacity="0.9"
      />
      <path
        d="M10 17 L10 14 M8.5 15 L10 13.5 L11.5 15"
        fill="none"
        stroke="#F5A623"
        strokeWidth="0.8"
        strokeLinecap="round"
        strokeLinejoin="round"
        opacity="0.9"
      />
      <path
        d="M3 10 L6 10 M5 8.5 L6.5 10 L5 11.5"
        fill="none"
        stroke="#F5A623"
        strokeWidth="0.8"
        strokeLinecap="round"
        strokeLinejoin="round"
        opacity="0.9"
      />
      <path
        d="M17 10 L14 10 M15 8.5 L13.5 10 L15 11.5"
        fill="none"
        stroke="#F5A623"
        strokeWidth="0.8"
        strokeLinecap="round"
        strokeLinejoin="round"
        opacity="0.9"
      />
      <circle cx="10" cy="10" r="1.5" fill="#F5A623" />
    </svg>
  );
}
