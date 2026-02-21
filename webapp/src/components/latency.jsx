import { useState } from "react";
import SettingsButton from "./SettingsButton";

let latencyData = {
  averageCount: 0,
  averageSum: 0,
  averageTime: 0,
  lastTime: new Date().getTime(),
};

export const getLatency = () => {
  let currentTime = new Date().getTime();
  let diffInMs = currentTime - latencyData.lastTime;
  latencyData.lastTime = currentTime;

  if (latencyData.averageTime == 0) latencyData.averageTime = diffInMs;

  latencyData.averageCount++;
  latencyData.averageSum += diffInMs;

  if (latencyData.averageCount >= 5) {
    latencyData.averageTime = latencyData.averageSum / latencyData.averageCount;

    latencyData.averageCount = 0;
    latencyData.averageSum = 0;
  }

  return latencyData.averageTime;
};

const MoveButton = () => {
  const [active, setActive] = useState(false);

  const toggleDrag = () => {
    setActive(!active);
    // Send message to Win32 overlay via WebView2 bridge
    if (window.chrome && window.chrome.webview) {
      window.chrome.webview.postMessage("toggle-drag");
    }
  };

  return (
    <button
      onClick={toggleDrag}
      className="flex items-center gap-1 transition-all rounded-xl"
      title={active ? "Lock position" : "Move / resize overlay"}
    >
      <svg
        width="18" height="18" viewBox="0 0 24 24" fill="none"
        stroke={active ? "#4ade80" : "#b1d0e7"} strokeWidth="2"
        strokeLinecap="round" strokeLinejoin="round"
      >
        <polyline points="5,9 2,12 5,15" />
        <polyline points="9,5 12,2 15,5" />
        <polyline points="15,19 12,22 9,19" />
        <polyline points="19,9 22,12 19,15" />
        <line x1="2" y1="12" x2="22" y2="12" />
        <line x1="12" y1="2" x2="12" y2="22" />
      </svg>
    </button>
  );
};

export const Latency = ({ value, settings, setSettings }) => {
  return (
    <div className={`flex gap-2 absolute text-[normal] right-2.5 top-2.5`}>
      <div className={'flex gap-1'}>
        <img className={`w-[1.3rem]`} src={`./assets/icons/gauge.svg`} />
        <span>{value.toFixed(0)}ms</span>
      </div>

      <MoveButton />
      <SettingsButton settings={settings} onSettingsChange={setSettings} />
    </div>
  );
};
