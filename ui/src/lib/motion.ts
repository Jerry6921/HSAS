import { createContext, useContext } from "react";

export const MotionPreference = createContext(false);
export const useWorkspaceMotion = () => useContext(MotionPreference);

export const flowEase = [0.22, 1, 0.36, 1] as const;
export const flowTransition = { duration: 0.42, ease: flowEase };
