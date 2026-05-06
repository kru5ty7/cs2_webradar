import { useRef } from "react";
import { getRadarPosition, teamEnum } from "../utilities/utilities";

const Bomb = ({ bombData, mapData, radarImage, localTeam, averageLatency, settings }) => {
  const radarPosition = getRadarPosition(mapData, bombData);

  const bombRef = useRef();
  const bombBounding = (bombRef.current &&
    bombRef.current.getBoundingClientRect()) || { width: 0, height: 0 };

  const radarImageBounding = (radarImage !== undefined &&
    radarImage.getBoundingClientRect()) || { width: 0, height: 0 };

  const radarImageTranslation = {
    x: radarImageBounding.width  * radarPosition.x - bombBounding.width  * 0.5,
    y: radarImageBounding.height * radarPosition.y - bombBounding.height * 0.5,
  };

  const scaledSize = 1.5 * settings.bombSize;

  // Resolved icon color — defused always green; otherwise use the user-chosen color
  // unless the local player is CT and bomb is unplanted (show as friendly blue)
  const isPlanted  = bombData.m_blow_time > 0;
  const isDefused  = bombData.m_is_defused;
  const isActive   = isPlanted && !isDefused;
  const userColor  = settings.bombColor || "#c90b0b";

  const iconColor = isDefused
    ? "#50904c"
    : (isPlanted
        ? userColor                                                    // ticking — user color
        : (localTeam == teamEnum.counterTerrorist ? "#6492b4" : userColor)); // carried

  // Pulse when carried too — helps locate the bomb at all times.
  // Pulse faster (animation-duration via inline style) when actively ticking.
  const showPulse  = settings.bombHighlight ?? true;

  return (
    <div
      ref={bombRef}
      className="absolute left-0 top-0"
      style={{
        width:     `${scaledSize}vw`,
        height:    `${scaledSize}vw`,
        transform: `translate(${radarImageTranslation.x}px, ${radarImageTranslation.y}px)`,
        transition: `transform ${averageLatency}ms linear`,
        zIndex: 10,
      }}
    >
      {/* Pulsing glow ring — slow when carried, fast when ticking */}
      {showPulse && (
        <div
          className="bomb-pulse absolute inset-0 rounded-full"
          style={{
            backgroundColor: iconColor,
            animationDuration: isActive ? "0.6s" : "1.6s",
          }}
        />
      )}

      {/* The C4 icon itself */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          backgroundColor: iconColor,
          WebkitMask: `url('./assets/icons/c4_sml.png') no-repeat center / contain`,
          mask:        `url('./assets/icons/c4_sml.png') no-repeat center / contain`,
          filter: showPulse
            ? `drop-shadow(0 0 4px ${iconColor})`
            : "none",
        }}
      />
    </div>
  );
};

export default Bomb;
