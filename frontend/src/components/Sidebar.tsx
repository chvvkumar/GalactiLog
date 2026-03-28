import { Component } from "solid-js";
import { useCatalog } from "../store/catalog";
import SearchBar from "./SearchBar";
import ObjectTypeToggles from "./ObjectTypeToggles";
import DateRangePicker from "./DateRangePicker";
import FilterToggles from "./FilterToggles";
import HardwareSelects from "./HardwareSelects";
import QualityFilters from "./QualityFilters";
import MetricFilters from "./MetricFilters";
import FitsQueryBuilder from "./FitsQueryBuilder";

const Sidebar: Component = () => {
  const { resetFilters } = useCatalog();

  return (
    <aside class="w-72 min-h-[calc(100vh-57px)] border-r border-theme-border p-4 space-y-6 overflow-y-auto">
      <SearchBar />
      <ObjectTypeToggles />
      <DateRangePicker />
      <FilterToggles />
      <HardwareSelects />
      <QualityFilters />
      <MetricFilters />
      <FitsQueryBuilder />
      <button
        onClick={resetFilters}
        class="w-full py-2 text-xs text-theme-text-secondary hover:text-theme-text-primary border border-theme-border hover:border-theme-border-em rounded transition-colors"
      >
        Reset Filters
      </button>
    </aside>
  );
};

export default Sidebar;
