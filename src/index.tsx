import { definePlugin, staticClasses } from "@decky/api";
import { FaGamepad } from "react-icons/fa";
import { MainView } from "./components/MainView";

export default definePlugin(() => {
  return {
    name: "Deck Controller",
    titleView: <span className={staticClasses.Title}>Deck Controller</span>,
    content: <MainView />,
    icon: <FaGamepad />,
  };
});
