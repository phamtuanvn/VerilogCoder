// Reference implementation used for local testbench validation only.
// NOT included in VerilogCoder dataset pipeline.

module TopModule(clk, reset, fcw, phr, phr_int, phr_frac);
input clk, reset;
input [31:0] fcw;
output [31:0] phr;
output [7:0] phr_int;
output [23:0] phr_frac;

reg [31:0] phr_reg;

always @(posedge clk)
    if (reset) phr_reg <= 32'h0;
    else       phr_reg <= phr_reg + fcw;

assign phr      = phr_reg;
assign phr_int  = phr_reg[31:24];
assign phr_frac = phr_reg[23:0];

endmodule
