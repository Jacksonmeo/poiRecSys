/** SiteSelection Artifact contract returned by the Agent runtime. */
export interface AnalysisMetadata {
  config_version: string
  dataset: string
  observation_period: string | null
}

export interface AreaCenter {
  longitude: number
  latitude: number
}

export interface AreaPolygon {
  type: "Polygon"
  coordinates: number[][][]
}

export interface CandidateArea {
  area_id: string
  display_name: string
  center?: AreaCenter
  polygon?: AreaPolygon
}

export interface AreaMetric {
  area_id?: string
  metric_id: string
  value: number
  description: string
  unit?: string
}

export interface AreaFlow {
  source_area: string
  target_area: string
  flow_count: number
  unique_users: number
  unique_sessions: number
}

export interface SiteSelectionArtifact {
  analysis_type: "site_selection"
  candidate_areas: CandidateArea[]
  metadata: AnalysisMetadata
  metrics: AreaMetric[]
  flows: AreaFlow[]
  summary: string | null
}
