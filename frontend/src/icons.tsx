import type { ReactNode } from 'react';

// Small inline icons; buttons using them keep an aria-label and a title.
function Icon({ children }: { children: ReactNode }) {
  return <svg className="icon" viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" focusable="false"
    fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">{children}</svg>;
}

export const CopyIcon = () => <Icon><rect x="9" y="9" width="11" height="11" rx="2" /><path d="M5 15V5a2 2 0 0 1 2-2h8" /></Icon>;
export const EditIcon = () => <Icon><path d="M4 20h4L19 9l-4-4L4 16z" /><path d="M14 6l4 4" /></Icon>;
export const DisableIcon = () => <Icon><circle cx="12" cy="12" r="9" /><path d="M6 18L18 6" /></Icon>;
export const EnableIcon = () => <Icon><circle cx="12" cy="12" r="9" /><path d="M8 12l3 3 5-6" /></Icon>;
export const TestIcon = () => <Icon><path d="M2 12h4l3-8 6 16 3-8h4" /></Icon>;
export const DeleteIcon = () => <Icon><path d="M4 7h16" /><path d="M9 7V4h6v3" /><path d="M6 7l1 13h10l1-13" /></Icon>;
export const AdoptIcon = () => <Icon><path d="M12 3v12" /><path d="M7 10l5 5 5-5" /><path d="M5 21h14" /></Icon>;
export const RunningIcon = () => <Icon><circle cx="12" cy="12" r="9" /><path d="M10 8l6 4-6 4z" fill="currentColor" /></Icon>;
export const StoppedIcon = () => <Icon><circle cx="12" cy="12" r="9" /><rect x="9" y="9" width="6" height="6" fill="currentColor" /></Icon>;
export const TerminatedIcon = () => <Icon><circle cx="12" cy="12" r="9" /><path d="M9 9l6 6M15 9l-6 6" /></Icon>;
export const OtherStateIcon = () => <Icon><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></Icon>;
