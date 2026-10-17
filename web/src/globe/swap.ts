import type { GroundPrimitive, Primitive, Scene } from "cesium";

type AnyPrimitive = Primitive | GroundPrimitive;

/**
 * Keep the old primitive on screen until the new primitive is ready.
 * This stops flicker when a layer changes its geometry.
 */
export class SwapPrimitive<P extends AnyPrimitive = AnyPrimitive> {
  private current: P | null = null;
  private pending: P | null = null;
  private visible = true;

  constructor(private readonly scene: Scene) {}

  /** Set the next primitive. Use null to remove all geometry. */
  set(next: P | null): void {
    if (this.pending) {
      this.scene.primitives.remove(this.pending);
      this.pending = null;
    }
    if (!next) {
      if (this.current) this.scene.primitives.remove(this.current);
      this.current = null;
      return;
    }
    next.show = this.visible;
    this.scene.primitives.add(next);
    this.pending = next;
  }

  /** Swap in the pending primitive when it is ready. Call this one time for each frame. */
  tick(): void {
    if (this.pending && this.pending.ready) {
      if (this.current) this.scene.primitives.remove(this.current);
      this.current = this.pending;
      this.pending = null;
    }
  }

  /** Return the primitive on screen, or null. */
  get active(): P | null {
    return this.current;
  }

  /** Return the newest primitive, which can be pending. */
  get latest(): P | null {
    return this.pending ?? this.current;
  }

  /** Show or hide the primitives. */
  setShow(v: boolean): void {
    this.visible = v;
    if (this.current) this.current.show = v;
    if (this.pending) this.pending.show = v;
  }
}
