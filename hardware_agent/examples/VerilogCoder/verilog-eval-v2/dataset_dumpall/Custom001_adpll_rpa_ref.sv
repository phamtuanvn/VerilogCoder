module TopModule (
    input         clk,
    input         reset,
    input  [31:0] fcw,
    output [31:0] phr,
    output [7:0]  phr_int,
    output [23:0] phr_frac
);
    reg [31:0] phr_reg;

    always @(posedge clk) begin
        if (reset)
            phr_reg <= 32'h0;
        else
            phr_reg <= phr_reg + fcw;
    end

    assign phr      = phr_reg;
    assign phr_int  = phr_reg[31:24];
    assign phr_frac = phr_reg[23:0];

endmodule
