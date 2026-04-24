import { useState } from "react";
import Player from "./player";
import Bomb from "./bomb";
import GrenadeLayer from "./GrenadeLayer";
import CalloutLayer from "./CalloutLayer";
import DroppedItemLayer from "./DroppedItemLayer";

const Radar = ({
  playerArray,
  radarImage,
  mapData,
  localTeam,
  averageLatency,
  bombData,
  grenades,
  dropped,
  settings
}) => {
  // Callback ref — triggers a re-render when the img element mounts,
  // so child components receive the actual DOM element (not null).
  const [radarImageEl, setRadarImageEl] = useState(undefined);

  return (
    <div id="radar" className="relative overflow-hidden max-h-full aspect-square w-auto">
      <img ref={setRadarImageEl} className="w-full h-auto" src={radarImage} />

      <CalloutLayer
        mapName={mapData?.name}
        radarImage={radarImageEl}
      />

      {playerArray.map((player) => (
        <Player
          key={player.m_idx}
          playerData={player}
          mapData={mapData}
          radarImage={radarImageEl}
          localTeam={localTeam}
          averageLatency={averageLatency}
          settings={settings}
        />
      ))}

      {bombData && (
        <Bomb
          bombData={bombData}
          mapData={mapData}
          radarImage={radarImageEl}
          localTeam={localTeam}
          averageLatency={averageLatency}
          settings={settings}
        />
      )}

      <GrenadeLayer
        grenades={grenades}
        mapData={mapData}
        radarImage={radarImageEl}
        settings={settings}
      />

      <DroppedItemLayer
        items={dropped}
        mapData={mapData}
        radarImage={radarImageEl}
      />
    </div>
  );
};

export default Radar;
