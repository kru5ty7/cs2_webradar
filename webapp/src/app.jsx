import ReactDOM from "react-dom/client";
import { useEffect, useState } from "react";
import "./App.css";
import PlayerCard from "./components/PlayerCard";
import Radar from "./components/Radar";
import ESP from "./components/ESP";
import { getLatency, Latency } from "./components/latency";
import MaskedIcon from "./components/maskedicon";

const CONNECTION_TIMEOUT = 5000;

/* change this to '1' if you want to use offline (your own pc only) */
const USE_LOCALHOST = 0;

/* you can get your public ip from https://ipinfo.io/ip */
const PUBLIC_IP = "192.168.31.17".trim();
const PORT = 22006;

/*
 * For ngrok: set VITE_WS_URL in a .env file or when starting vite, e.g.:
 *   VITE_WS_URL=wss://xxxx-xxxx.ngrok-free.app/cs2_webradar
 * This tells the frontend where the WebSocket ngrok tunnel is.
 */
const NGROK_WS_URL = import.meta.env.VITE_WS_URL || null;

const EFFECTIVE_IP = USE_LOCALHOST ? "localhost" : window.location.hostname;

// True when running inside the pywebview ESP overlay (WebView2 host)
const IS_OVERLAY = !!(window.chrome?.webview);

const DEFAULT_SETTINGS = {
  dotSize: 1,
  bombSize: 0.5,
  showAllNames: false,
  showEnemyNames: true,
  showViewCones: false,
  showSmoke: true,
  showMolly: true,
  showFlash: true,
  showCallouts: true,
};

const loadSettings = () => {
  const savedSettings = localStorage.getItem("radarSettings");
  return savedSettings ? JSON.parse(savedSettings) : DEFAULT_SETTINGS;
};

const App = () => {
  const [averageLatency, setAverageLatency] = useState(0);
  const [playerArray, setPlayerArray] = useState([]);
  const [mapData, setMapData] = useState();
  const [localTeam, setLocalTeam] = useState();
  const [bombData, setBombData] = useState();
  const [grenades, setGrenades] = useState([]);
  const [dropped, setDropped]   = useState([]);
  const [settings, setSettings] = useState(loadSettings());
  const [viewMatrix, setViewMatrix] = useState([]);
  const [bannerOpened, setBannerOpened] = useState(true)

  // Save settings to local storage whenever they change
  useEffect(() => {
    localStorage.setItem("radarSettings", JSON.stringify(settings));
  }, [settings]);

  useEffect(() => {
    const fetchData = async () => {
      let webSocket = null;
      let webSocketURL = null;
      let connectionTimeout = null;

      if (!webSocket) {
        try {
          if (NGROK_WS_URL) {
            webSocketURL = NGROK_WS_URL;
          } else if (USE_LOCALHOST) {
            webSocketURL = `ws://localhost:${PORT}/cs2_webradar`;
          } else {
            webSocketURL = `ws://${EFFECTIVE_IP}:${PORT}/cs2_webradar`;
          }

          if (!webSocketURL) return;
          webSocket = new WebSocket(webSocketURL);
        } catch (error) {
          document.getElementsByClassName(
            "radar_message"
          )[0].textContent = `${error}`;
        }
      }

      connectionTimeout = setTimeout(() => {
        webSocket.close();
      }, CONNECTION_TIMEOUT);

      webSocket.onopen = async () => {
        clearTimeout(connectionTimeout);
        console.info("connected to the web socket");
      };

      webSocket.onclose = async () => {
        clearTimeout(connectionTimeout);
        console.error("disconnected from the web socket");
      };

      webSocket.onerror = async (error) => {
        clearTimeout(connectionTimeout);
        document.getElementsByClassName(
          "radar_message"
        )[0].textContent = `WebSocket connection to '${webSocketURL}' failed. Please check the IP address and try again`;
        console.error(error);
      };

      webSocket.onmessage = async (event) => {
        setAverageLatency(getLatency());

        const raw = typeof event.data === "string" ? event.data : await event.data.text();
        const parsedData = JSON.parse(raw);
        setPlayerArray(parsedData.m_players);
        setLocalTeam(parsedData.m_local_team);
        setBombData(parsedData.m_bomb);
        setGrenades(parsedData.m_grenades || []);
        setDropped(parsedData.m_dropped   || []);
        setViewMatrix(parsedData.m_view_matrix || []);

        const map = parsedData.m_map;
        if (map !== "invalid") {
          try {
            const res = await fetch(`data/${map}/data.json`);
            if (res.ok) {
              setMapData({ ...(await res.json()), name: map });
              document.body.style.backgroundImage = IS_OVERLAY
                ? "none"
                : `url(./data/${map}/background.png)`;
            } else {
              console.warn(`No map data for "${map}" (${res.status})`);
            }
          } catch (e) {
            console.warn(`Failed to load map data for "${map}":`, e);
          }
        }
      };
    };

    fetchData();
  }, []);

  // ── Overlay (ESP) mode ────────────────────────────────────────────────────
  if (IS_OVERLAY) {
    return (
      <div style={{ width: "100vw", height: "100vh", background: "transparent" }}>
        <ESP
          playerArray={playerArray}
          localTeam={localTeam}
          viewMatrix={viewMatrix}
        />
        {/* Bomb timer shown in overlay too */}
        {bombData && bombData.m_blow_time > 0 && !bombData.m_is_defused && (
          <div style={{
            position: "fixed", top: 12, left: "50%", transform: "translateX(-50%)",
            display: "flex", alignItems: "center", gap: 6,
            background: "rgba(0,0,0,0.6)", borderRadius: 6, padding: "4px 10px",
            color: "#fff", fontFamily: "monospace", fontSize: 18, zIndex: 9999,
          }}>
            <MaskedIcon
              path={`./assets/icons/c4_sml.png`}
              height={24}
              color={
                (bombData.m_is_defusing &&
                  bombData.m_blow_time - bombData.m_defuse_time > 0 &&
                  `bg-radar-green`) ||
                (bombData.m_blow_time - bombData.m_defuse_time < 0 &&
                  `bg-radar-red`) ||
                `bg-radar-secondary`
              }
            />
            <span>
              {`${bombData.m_blow_time.toFixed(1)}s`}
              {bombData.m_is_defusing && ` (${bombData.m_defuse_time.toFixed(1)}s)`}
            </span>
          </div>
        )}
      </div>
    );
  }

  // ── Normal radar mode ─────────────────────────────────────────────────────
  return (
    <div className="w-screen h-screen flex flex-col"
      style={{
        background: `radial-gradient(50% 50% at 50% 50%, rgba(20, 40, 55, 0.95) 0%, rgba(7, 20, 30, 0.95) 100%)`,
        backdropFilter: `blur(7.5px)`,
      }}
    >
      <div className={`w-full h-full flex flex-col justify-center overflow-hidden relative`}>
        {bombData && bombData.m_blow_time > 0 && !bombData.m_is_defused && (
          <div className={`absolute left-1/2 top-2 flex-col items-center gap-1 z-50`}>
            <div className={`flex justify-center items-center gap-1`}>
              <MaskedIcon
                path={`./assets/icons/c4_sml.png`}
                height={32}
                color={
                  (bombData.m_is_defusing &&
                    bombData.m_blow_time - bombData.m_defuse_time > 0 &&
                    `bg-radar-green`) ||
                  (bombData.m_blow_time - bombData.m_defuse_time < 0 &&
                    `bg-radar-red`) ||
                  `bg-radar-secondary`
                }
              />
              <span>{`${bombData.m_blow_time.toFixed(1)}s ${(bombData.m_is_defusing &&
                `(${bombData.m_defuse_time.toFixed(1)}s)`) ||
                ""
                }`}</span>
            </div>
          </div>
        )}

        {/* Latency/settings overlay — absolutely positioned, not in flex flow */}
        <Latency
          value={averageLatency}
          settings={settings}
          setSettings={setSettings}
        />

        <div className={`flex items-center justify-evenly w-full h-full overflow-hidden`}>
          <ul id="terrorist" className="lg:flex hidden flex-col justify-center gap-2 m-0 p-0 shrink-0 overflow-hidden max-h-full">
            {playerArray
              .filter((player) => player.m_team == 2)
              .map((player) => (
                <PlayerCard
                  right={false}
                  key={player.m_idx}
                  playerData={player}
                />
              ))}
          </ul>

          {(playerArray.length > 0 && mapData && (
            <Radar
              playerArray={playerArray}
              radarImage={`./data/${mapData.name}/radar.png`}
              mapData={mapData}
              localTeam={localTeam}
              averageLatency={averageLatency}
              bombData={bombData}
              grenades={grenades}
              dropped={dropped}
              settings={settings}
            />
          )) || (
            <div id="radar" className="relative flex items-center justify-center">
              <h1 className="radar_message">
                Connected! Waiting for data from usermode
              </h1>
            </div>
          )}

          <ul
            id="counterTerrorist"
            className="lg:flex hidden flex-col justify-center gap-2 m-0 p-0 shrink-0 overflow-hidden max-h-full"
          >
            {playerArray
              .filter((player) => player.m_team == 3)
              .map((player) => (
                <PlayerCard
                  right={true}
                  key={player.m_idx}
                  playerData={player}
                  settings={settings}
                />
              ))}
          </ul>
        </div>
      </div>
    </div>
  );
};

export default App;
