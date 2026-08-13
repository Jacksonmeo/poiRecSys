import { shallowMount } from "@vue/test-utils"
import { createPinia } from "pinia"
import { describe, expect, it } from "vitest"
import EvidencePanel from "./EvidencePanel.vue"
import SpatialCanvas from "./SpatialCanvas.vue"
import SpatialWorkspace from "@/views/workspace/SpatialWorkspace.vue"

describe("SpatialWorkspace", () => {
  it("keeps task, map, and evidence as three independent workspace regions", () => {
    const wrapper = shallowMount(SpatialWorkspace, { global: { plugins: [createPinia()] } })

    expect(wrapper.attributes("data-testid")).toBe("spatial-workspace")
    expect(wrapper.findComponent(SpatialCanvas).exists()).toBe(true)
    expect(wrapper.findComponent(EvidencePanel).exists()).toBe(false)

    const canvas = shallowMount(SpatialCanvas, { global: { plugins: [createPinia()] } })
    expect(canvas.find(".spatial-canvas__bar").exists()).toBe(false)
    expect(canvas.find(".spatial-canvas__map").exists()).toBe(true)
  })
})
