import { useRef } from "react";
import Player from "./player";
import Bomb from "./bomb";
import GrenadeLayer from "./GrenadeLayer";

const Radar = ({
  playerArray,
  radarImage,
  mapData,
  localTeam,
  averageLatency,
  bombData,
  grenades,
  settings
}) => {
  const radarImageRef = useRef();

  return (
    <div id="radar" className={`relative overflow-hidden origin-center`}>
      <img ref={radarImageRef} className={`w-full h-auto`} src={radarImage} />

      {playerArray.map((player) => (
        <Player
          key={player.m_idx}
          playerData={player}
          mapData={mapData}
          radarImage={radarImageRef.current}
          localTeam={localTeam}
          averageLatency={averageLatency}
          settings={settings}
        />
      ))}

      {bombData && (
        <Bomb
          bombData={bombData}
          mapData={mapData}
          radarImage={radarImageRef.current}
          localTeam={localTeam}
          averageLatency={averageLatency}
          settings={settings}
        />
      )}

      <GrenadeLayer
        grenades={grenades}
        mapData={mapData}
        radarImage={radarImageRef.current}
      />
    </div>
  );
};

export default Radar;