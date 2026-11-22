export const worldLayers = ['physics', 'chemistry', 'astronomy', 'geological', 'climate', 'ecology', 'civilization'] as const
export type WorldLayer = typeof worldLayers[number]
