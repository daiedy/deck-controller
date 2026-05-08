import React from "react";

type FC = React.FC<Record<string, unknown>>;

const makeComponent = (name: string): FC => {
  const Component: FC = ({ children, ...props }) =>
    React.createElement("div", { "data-testid": name, ...props }, children);
  Component.displayName = name;
  return Component;
};

export const PanelSection = makeComponent("PanelSection");
export const PanelSectionRow = makeComponent("PanelSectionRow");
export const ButtonItem = makeComponent("ButtonItem");
export const Field = makeComponent("Field");
export const ToggleField = makeComponent("ToggleField");
export const SliderField = makeComponent("SliderField");
export const DropdownItem = makeComponent("DropdownItem");
export const TextField = makeComponent("TextField");
